"""
tests/test_safety_guard.py — SafetyGuard ユニットテスト

サーキットブレーカー・レート制限・設定読み込みを検証する。
"""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def safety_config_dir(tmp_path: Path) -> Path:
    """テスト用 safety.yaml を含む config ディレクトリを作成する fixture。"""
    config = {
        "circuit_breaker": {
            "failure_threshold": 3,
            "recovery_timeout": 10,  # テスト用: 10秒
        },
        "skill_limits": {
            "browse_source": {
                "max_per_hour": 5,
                "max_per_day": 20,
            },
            "llm_call": {
                "max_per_hour": 10,
                "max_per_day": 50,
            },
        },
        "blacklist": {"domains": [], "urls": []},
        "output_validation": {
            "max_content_length": 50000,
            "require_source_url": True,
            "min_content_length": 10,
        },
        "on_error": {
            "log_full_trace": True,
            "notify_discord": False,
            "stop_on_critical": True,
        },
    }
    (tmp_path / "safety.yaml").write_text(yaml.dump(config))
    return tmp_path


class TestSafetyGuardImport:
    """SafetyGuard / SafetyResult のインポートを検証"""

    def test_import_safety_result(self):
        """SafetyResult が正常にインポートできる"""
        from core.safety_guard import SafetyResult
        assert SafetyResult is not None

    def test_import_safety_guard(self):
        """SafetyGuard が正常にインポートできる"""
        from core.safety_guard import SafetyGuard
        assert SafetyGuard is not None


class TestSafetyResultCreation:
    """SafetyResult の生成と属性を検証"""

    def test_allowed_result(self):
        """allowed=True の SafetyResult を生成できる"""
        from core.safety_guard import SafetyResult

        result = SafetyResult(allowed=True)
        assert result.allowed is True
        assert result.reason is None
        assert result.wait_seconds == 0

    def test_denied_result(self):
        """allowed=False の SafetyResult を生成できる"""
        from core.safety_guard import SafetyResult

        result = SafetyResult(allowed=False, reason="レート制限超過", wait_seconds=60)
        assert result.allowed is False
        assert result.reason == "レート制限超過"
        assert result.wait_seconds == 60

    def test_safety_result_is_frozen(self):
        """SafetyResult はイミュータブル（frozen）である"""
        from core.safety_guard import SafetyResult

        result = SafetyResult(allowed=True)
        with pytest.raises(Exception):  # FrozenInstanceError または AttributeError
            result.allowed = False  # type: ignore


class TestSafetyGuardInit:
    """SafetyGuard の初期化を検証"""

    def test_init_loads_config(self, safety_config_dir: Path):
        """設定ファイルを読み込んで初期化できる"""
        from core.safety_guard import SafetyGuard

        guard = SafetyGuard(config_dir=safety_config_dir)
        assert guard is not None

    def test_init_missing_config_raises(self, tmp_path: Path):
        """設定ファイルが存在しない場合は FileNotFoundError が発生する"""
        from core.safety_guard import SafetyGuard

        with pytest.raises(FileNotFoundError):
            SafetyGuard(config_dir=tmp_path)


class TestSafetyGuardCheck:
    """SafetyGuard.check メソッドを検証"""

    def test_check_unknown_skill_allowed(self, safety_config_dir: Path):
        """skill_limits に登録されていない Skill は制限なし（allowed=True）"""
        from core.safety_guard import SafetyGuard

        guard = SafetyGuard(config_dir=safety_config_dir)
        result = guard.check("unknown_skill")

        assert result.allowed is True

    def test_check_allowed_when_no_executions(self, safety_config_dir: Path):
        """実行回数が 0 の場合は allowed=True"""
        from core.safety_guard import SafetyGuard

        guard = SafetyGuard(config_dir=safety_config_dir)
        result = guard.check("browse_source")

        assert result.allowed is True

    def test_check_denied_when_circuit_open(self, safety_config_dir: Path):
        """サーキットが開いている場合は allowed=False"""
        from core.safety_guard import SafetyGuard

        guard = SafetyGuard(config_dir=safety_config_dir)
        # failure_threshold=3 なので 3 回失敗させる
        for _ in range(3):
            guard.record_failure("browse_source")

        result = guard.check("browse_source")
        assert result.allowed is False
        assert result.reason is not None

    def test_check_denied_when_hourly_limit_exceeded(self, safety_config_dir: Path):
        """時間制限を超えた場合は allowed=False"""
        from core.safety_guard import SafetyGuard

        guard = SafetyGuard(config_dir=safety_config_dir)
        # max_per_hour=5 なので 5 回成功記録
        for _ in range(5):
            guard.record_success("browse_source")

        result = guard.check("browse_source")
        assert result.allowed is False
        assert result.reason is not None

    def test_check_denied_when_daily_limit_exceeded(self, safety_config_dir: Path):
        """日次制限を超えた場合は allowed=False"""
        from core.safety_guard import SafetyGuard

        guard = SafetyGuard(config_dir=safety_config_dir)
        # max_per_day=20 なので 20 回成功記録
        for _ in range(20):
            guard.record_success("browse_source")

        result = guard.check("browse_source")
        assert result.allowed is False

    def test_check_allowed_within_limits(self, safety_config_dir: Path):
        """制限内の実行回数なら allowed=True"""
        from core.safety_guard import SafetyGuard

        guard = SafetyGuard(config_dir=safety_config_dir)
        # max_per_hour=5 の範囲内
        for _ in range(3):
            guard.record_success("browse_source")

        result = guard.check("browse_source")
        assert result.allowed is True


class TestSafetyGuardCircuitBreaker:
    """サーキットブレーカーの動作を検証"""

    def test_circuit_closed_initially(self, safety_config_dir: Path):
        """初期状態でサーキットは閉じている（is_circuit_open = False）"""
        from core.safety_guard import SafetyGuard

        guard = SafetyGuard(config_dir=safety_config_dir)
        assert guard.is_circuit_open("browse_source") is False

    def test_circuit_opens_after_threshold(self, safety_config_dir: Path):
        """failure_threshold 回の失敗でサーキットが開く"""
        from core.safety_guard import SafetyGuard

        guard = SafetyGuard(config_dir=safety_config_dir)
        # failure_threshold=3
        guard.record_failure("browse_source")
        guard.record_failure("browse_source")
        assert guard.is_circuit_open("browse_source") is False

        guard.record_failure("browse_source")
        assert guard.is_circuit_open("browse_source") is True

    def test_circuit_resets_on_success(self, safety_config_dir: Path):
        """成功でサーキットブレーカーがリセットされる（失敗カウントが 0 になる）"""
        from core.safety_guard import SafetyGuard

        guard = SafetyGuard(config_dir=safety_config_dir)
        guard.record_failure("browse_source")
        guard.record_failure("browse_source")
        guard.record_success("browse_source")

        # 失敗カウントがリセットされたので再び 2 回失敗しても開かない
        guard.record_failure("browse_source")
        guard.record_failure("browse_source")
        assert guard.is_circuit_open("browse_source") is False

    def test_circuit_auto_resets_after_recovery_timeout(self, safety_config_dir: Path):
        """recovery_timeout 経過後はサーキットが自動リセットされる"""
        import time
        from core.safety_guard import SafetyGuard
        from datetime import datetime, timedelta, timezone

        guard = SafetyGuard(config_dir=safety_config_dir)
        # サーキットを開く
        for _ in range(3):
            guard.record_failure("browse_source")

        assert guard.is_circuit_open("browse_source") is True

        # recovery_timeout=10 秒を過去に設定（モックして時刻を操作）
        past_time = datetime.now(timezone.utc) - timedelta(seconds=11)
        guard._circuit_open_at["browse_source"] = past_time

        # 自動リセット確認
        assert guard.is_circuit_open("browse_source") is False

    def test_circuit_independent_per_skill(self, safety_config_dir: Path):
        """サーキットブレーカーは Skill ごとに独立している"""
        from core.safety_guard import SafetyGuard

        guard = SafetyGuard(config_dir=safety_config_dir)
        for _ in range(3):
            guard.record_failure("browse_source")

        # browse_source はサーキット開
        assert guard.is_circuit_open("browse_source") is True
        # llm_call は影響を受けない
        assert guard.is_circuit_open("llm_call") is False


class TestSafetyGuardRecordSuccess:
    """record_success メソッドを検証"""

    def test_record_success_adds_execution_time(self, safety_config_dir: Path):
        """成功記録で実行時刻が追加される"""
        from core.safety_guard import SafetyGuard

        guard = SafetyGuard(config_dir=safety_config_dir)
        guard.record_success("browse_source")

        assert len(guard._hourly_counts["browse_source"]) == 1
        assert len(guard._daily_counts["browse_source"]) == 1

    def test_record_success_resets_failure_count(self, safety_config_dir: Path):
        """成功記録で失敗カウントがリセットされる"""
        from core.safety_guard import SafetyGuard

        guard = SafetyGuard(config_dir=safety_config_dir)
        guard.record_failure("browse_source")
        guard.record_failure("browse_source")
        guard.record_success("browse_source")

        assert guard._failure_counts.get("browse_source", 0) == 0


class TestSafetyGuardRecordFailure:
    """record_failure メソッドを検証"""

    def test_record_failure_increments_count(self, safety_config_dir: Path):
        """失敗記録で連続失敗数がインクリメントされる"""
        from core.safety_guard import SafetyGuard

        guard = SafetyGuard(config_dir=safety_config_dir)
        guard.record_failure("browse_source")
        guard.record_failure("browse_source")

        assert guard._failure_counts.get("browse_source", 0) == 2

    def test_record_failure_opens_circuit_at_threshold(self, safety_config_dir: Path):
        """failure_threshold 到達でサーキットが開く"""
        from core.safety_guard import SafetyGuard

        guard = SafetyGuard(config_dir=safety_config_dir)
        for _ in range(3):
            guard.record_failure("browse_source")

        assert "browse_source" in guard._circuit_open_at


class TestSafetyGuardCleanup:
    """_cleanup_old_records メソッドを検証"""

    def test_cleanup_removes_old_hourly_records(self, safety_config_dir: Path):
        """1時間以上前の記録が hourly_counts から除去される"""
        from core.safety_guard import SafetyGuard
        from datetime import datetime, timedelta, timezone

        guard = SafetyGuard(config_dir=safety_config_dir)

        # 2時間前の記録を直接設定
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        guard._hourly_counts["browse_source"] = [old_time]
        guard._daily_counts["browse_source"] = []

        guard._cleanup_old_records("browse_source")

        assert len(guard._hourly_counts["browse_source"]) == 0

    def test_cleanup_removes_old_daily_records(self, safety_config_dir: Path):
        """24時間以上前の記録が daily_counts から除去される"""
        from core.safety_guard import SafetyGuard
        from datetime import datetime, timedelta, timezone

        guard = SafetyGuard(config_dir=safety_config_dir)

        # 25時間前の記録を直接設定
        old_time = datetime.now(timezone.utc) - timedelta(hours=25)
        guard._hourly_counts["browse_source"] = []
        guard._daily_counts["browse_source"] = [old_time]

        guard._cleanup_old_records("browse_source")

        assert len(guard._daily_counts["browse_source"]) == 0

    def test_cleanup_keeps_recent_records(self, safety_config_dir: Path):
        """直近の記録は除去されない"""
        from core.safety_guard import SafetyGuard
        from datetime import datetime, timedelta, timezone

        guard = SafetyGuard(config_dir=safety_config_dir)

        # 30分前（直近）の記録
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        guard._hourly_counts["browse_source"] = [recent_time]
        guard._daily_counts["browse_source"] = [recent_time]

        guard._cleanup_old_records("browse_source")

        assert len(guard._hourly_counts["browse_source"]) == 1
        assert len(guard._daily_counts["browse_source"]) == 1
