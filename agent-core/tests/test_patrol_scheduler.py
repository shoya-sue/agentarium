"""
tests/test_patrol_scheduler.py — PatrolScheduler ユニットテスト

YAML 設定の読み込み・活動時間判定・ソース状態管理を検証する。
"""

import sys
from datetime import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def patrol_config_dir(tmp_path: Path) -> Path:
    """テスト用 patrol.yaml を含む config ディレクトリを作成する fixture。"""
    schedules_dir = tmp_path / "schedules"
    schedules_dir.mkdir(parents=True)

    config = {
        "patrol": [
            {"source": "source_a", "interval_min": 60, "enabled": True},
            {"source": "source_b", "interval_min": 120, "enabled": True},
            {"source": "source_disabled", "interval_min": 30, "enabled": False},
        ],
        "scheduler": {
            "run_all_on_startup": False,
            "priority_order": ["source_b", "source_a"],
            "max_concurrent": 1,
            "retry_on_failure": True,
            "retry_delay_sec": 1,
            "max_retries": 1,
            "active_hours": [{"start": "07:00", "end": "01:00"}],
        },
    }
    (schedules_dir / "patrol.yaml").write_text(yaml.dump(config))
    return tmp_path


class TestPatrolSchedulerConfig:
    """PatrolScheduler の設定読み込みを検証"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from scheduler.patrol_scheduler import PatrolScheduler
        assert PatrolScheduler is not None

    def test_load_config_creates_source_states(self, patrol_config_dir: Path):
        """設定読み込みで SourceState が作成される"""
        from scheduler.patrol_scheduler import PatrolScheduler

        scheduler = PatrolScheduler(config_dir=patrol_config_dir)
        scheduler._load_config()

        states = scheduler.get_states()
        assert "source_a" in states
        assert "source_b" in states
        assert "source_disabled" in states

    def test_disabled_source_not_due(self, patrol_config_dir: Path):
        """無効ソース（enabled: false）は is_due が False を返す"""
        from scheduler.patrol_scheduler import PatrolScheduler
        from datetime import datetime, timezone

        scheduler = PatrolScheduler(config_dir=patrol_config_dir)
        scheduler._load_config()

        states = scheduler.get_states()
        now = datetime.now(timezone.utc)
        assert states["source_disabled"].is_due(now) is False

    def test_enabled_source_without_last_run_is_due(self, patrol_config_dir: Path):
        """last_run_at が None の有効ソースは is_due が True を返す"""
        from scheduler.patrol_scheduler import PatrolScheduler
        from datetime import datetime, timezone

        scheduler = PatrolScheduler(config_dir=patrol_config_dir)
        scheduler._load_config()

        states = scheduler.get_states()
        now = datetime.now(timezone.utc)
        assert states["source_a"].is_due(now) is True

    def test_source_not_due_within_interval(self, patrol_config_dir: Path):
        """実行直後のソースは is_due が False を返す"""
        from scheduler.patrol_scheduler import PatrolScheduler
        from datetime import datetime, timezone, timedelta

        scheduler = PatrolScheduler(config_dir=patrol_config_dir)
        scheduler._load_config()

        states = scheduler.get_states()
        source_a = states["source_a"]

        # 30 分前に実行済み（interval_min = 60）
        last_run = datetime.now(timezone.utc) - timedelta(minutes=30)
        updated = source_a.with_last_run(last_run)

        now = datetime.now(timezone.utc)
        assert updated.is_due(now) is False

    def test_source_due_after_interval(self, patrol_config_dir: Path):
        """interval_min 経過後は is_due が True を返す"""
        from scheduler.patrol_scheduler import PatrolScheduler
        from datetime import datetime, timezone, timedelta

        scheduler = PatrolScheduler(config_dir=patrol_config_dir)
        scheduler._load_config()

        states = scheduler.get_states()
        source_a = states["source_a"]

        # 70 分前に実行済み（interval_min = 60）
        last_run = datetime.now(timezone.utc) - timedelta(minutes=70)
        updated = source_a.with_last_run(last_run)

        now = datetime.now(timezone.utc)
        assert updated.is_due(now) is True


class TestSourceStateImmutability:
    """SourceState の不変パターンを検証"""

    def test_with_last_run_returns_new_instance(self):
        """with_last_run は新しいインスタンスを返す"""
        from scheduler.patrol_scheduler import SourceState
        from datetime import datetime, timezone

        state = SourceState(source_id="test", interval_min=60, enabled=True)
        now = datetime.now(timezone.utc)
        new_state = state.with_last_run(now)

        assert new_state is not state
        assert new_state.last_run_at == now
        assert new_state.consecutive_failures == 0
        assert state.last_run_at is None  # 元のインスタンスは変更されない

    def test_with_failure_increments_counter(self):
        """with_failure は連続失敗数をインクリメントした新インスタンスを返す"""
        from scheduler.patrol_scheduler import SourceState

        state = SourceState(source_id="test", interval_min=60, enabled=True)
        failed = state.with_failure()
        failed_again = failed.with_failure()

        assert failed.consecutive_failures == 1
        assert failed_again.consecutive_failures == 2
        assert state.consecutive_failures == 0  # 元は変更されない


class TestActiveHours:
    """活動時間帯チェックを検証"""

    def _make_scheduler(self, active_hours: list) -> "PatrolScheduler":
        """active_hours を指定したスケジューラを作成する。"""
        from scheduler.patrol_scheduler import PatrolScheduler

        scheduler = PatrolScheduler.__new__(PatrolScheduler)
        scheduler._scheduler_cfg = {"active_hours": active_hours}
        scheduler._states = {}
        scheduler._running = False
        scheduler._task = None
        return scheduler

    def test_no_active_hours_always_active(self):
        """active_hours が未設定なら常に True"""
        from scheduler.patrol_scheduler import PatrolScheduler

        scheduler = PatrolScheduler.__new__(PatrolScheduler)
        scheduler._scheduler_cfg = {}
        assert scheduler._is_active_hour() is True

    def test_midnight_spanning_active_hours(self):
        """深夜をまたぐ active_hours（07:00〜01:00）を正しく判定する"""
        from scheduler.patrol_scheduler import _parse_time

        start_t = _parse_time("07:00")
        end_t = _parse_time("01:00")

        # start > end のケース（深夜またぎ）
        assert start_t > end_t

        # 08:00 は活動時間内
        current = time(8, 0)
        assert current >= start_t or current <= end_t  # True (current >= start)

        # 03:00 は非活動時間
        current_inactive = time(3, 0)
        assert not (current_inactive >= start_t or current_inactive <= end_t)

    def test_parse_time_valid(self):
        """正常な時刻文字列を正しくパースする"""
        from scheduler.patrol_scheduler import _parse_time

        assert _parse_time("07:00") == time(7, 0)
        assert _parse_time("23:59") == time(23, 59)
        assert _parse_time("00:00") == time(0, 0)

    def test_parse_time_invalid_returns_midnight(self):
        """不正な時刻文字列はミッドナイト(00:00)を返す"""
        from scheduler.patrol_scheduler import _parse_time

        assert _parse_time("invalid") == time(0, 0)
        assert _parse_time("") == time(0, 0)
        assert _parse_time("25:00") == time(0, 0)


class TestPatrolSchedulerRun:
    """PatrolScheduler の実行フローを検証"""

    @pytest.mark.asyncio
    async def test_run_source_calls_handler(self, patrol_config_dir: Path):
        """_run_source がハンドラを呼び出す"""
        from scheduler.patrol_scheduler import PatrolScheduler, SourceState
        from datetime import datetime, timezone

        calls = []

        async def mock_handler(source_id: str):
            calls.append(source_id)
            return [{"title": "item"}]

        scheduler = PatrolScheduler(
            config_dir=patrol_config_dir,
            handler=mock_handler,
        )
        scheduler._load_config()

        state = SourceState(
            source_id="source_a", interval_min=60, enabled=True
        )
        await scheduler._run_source(state)

        assert "source_a" in calls
        # last_run_at が更新されている
        assert scheduler._states["source_a"].last_run_at is not None

    @pytest.mark.asyncio
    async def test_run_source_retries_on_failure(self, patrol_config_dir: Path):
        """ハンドラ失敗時にリトライする"""
        from scheduler.patrol_scheduler import PatrolScheduler, SourceState

        call_count = [0]

        async def failing_handler(source_id: str):
            call_count[0] += 1
            raise RuntimeError("テスト失敗")

        scheduler = PatrolScheduler(
            config_dir=patrol_config_dir,
            handler=failing_handler,
        )
        scheduler._load_config()
        # retry_delay_sec=1, max_retries=1 なので計2回呼ばれる

        state = SourceState(
            source_id="source_a", interval_min=60, enabled=True
        )
        # retry_delay_sec を 0 に上書き（テスト高速化）
        scheduler._scheduler_cfg["retry_delay_sec"] = 0
        await scheduler._run_source(state)

        # 1回目 + リトライ1回 = 2回
        assert call_count[0] == 2


class TestWriteStates:
    """PatrolScheduler._write_states を検証"""

    def test_write_states_creates_json_file(
        self, tmp_path: Path, patrol_config_dir: Path
    ):
        """_write_states が states.json を正しく生成する"""
        import json
        from scheduler.patrol_scheduler import PatrolScheduler

        data_dir = tmp_path / "data"
        scheduler = PatrolScheduler(
            config_dir=patrol_config_dir,
            data_dir=data_dir,
        )
        scheduler._load_config()
        scheduler._write_states()

        states_file = data_dir / "scheduler" / "states.json"
        assert states_file.exists()

        payload = json.loads(states_file.read_text(encoding="utf-8"))
        assert "updated_at" in payload
        assert "sources" in payload
        assert isinstance(payload["sources"], list)
        assert len(payload["sources"]) == 3  # source_a, source_b, source_disabled

    def test_write_states_contains_correct_fields(
        self, tmp_path: Path, patrol_config_dir: Path
    ):
        """生成された JSON の各ソースに必要なフィールドが含まれる"""
        import json
        from scheduler.patrol_scheduler import PatrolScheduler

        data_dir = tmp_path / "data"
        scheduler = PatrolScheduler(
            config_dir=patrol_config_dir,
            data_dir=data_dir,
        )
        scheduler._load_config()
        scheduler._write_states()

        payload = json.loads(
            (data_dir / "scheduler" / "states.json").read_text(encoding="utf-8")
        )
        source_ids = {s["source_id"] for s in payload["sources"]}
        assert "source_a" in source_ids
        assert "source_disabled" in source_ids

        for s in payload["sources"]:
            assert "source_id" in s
            assert "enabled" in s
            assert "interval_min" in s
            assert "last_run_at" in s
            assert "consecutive_failures" in s

    def test_write_states_no_data_dir_skips_silently(
        self, patrol_config_dir: Path
    ):
        """data_dir が未設定の場合、_write_states は何もしない"""
        from scheduler.patrol_scheduler import PatrolScheduler

        scheduler = PatrolScheduler(config_dir=patrol_config_dir)  # data_dir=None
        scheduler._load_config()
        # 例外が発生しないことを確認
        scheduler._write_states()

    @pytest.mark.asyncio
    async def test_write_states_called_after_run_source(
        self, tmp_path: Path, patrol_config_dir: Path
    ):
        """_run_source 後に states.json が更新される"""
        import json
        from scheduler.patrol_scheduler import PatrolScheduler, SourceState

        data_dir = tmp_path / "data"

        async def mock_handler(source_id: str):
            return [{"title": "item"}]

        scheduler = PatrolScheduler(
            config_dir=patrol_config_dir,
            handler=mock_handler,
            data_dir=data_dir,
        )
        scheduler._load_config()

        state = SourceState(source_id="source_a", interval_min=60, enabled=True)
        await scheduler._run_source(state)

        states_file = data_dir / "scheduler" / "states.json"
        assert states_file.exists()

        payload = json.loads(states_file.read_text(encoding="utf-8"))
        source_a = next(s for s in payload["sources"] if s["source_id"] == "source_a")
        assert source_a["last_run_at"] is not None
        assert source_a["consecutive_failures"] == 0
