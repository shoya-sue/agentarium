"""
tests/integration/test_agent_loop_stability.py — AgentLoop 長時間稼働テスト

実サービス不要（全 Skill をモックで置き換え）。
AgentLoop + PresenceMonitor の協調動作と安定稼働を検証する。

テストシナリオ:
  1. N サイクル正常完了
  2. PresenceMonitor が AgentLoop と同時起動・停止
  3. キャラクター状態 (L3/L4/L5) の逐次 store → recall
  4. Skill 実行エラー時もループが継続
  5. CancelledError で両コンポーネントが正常終了
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# src/ を Python パスに追加
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from scheduler.agent_loop import AgentLoop
from scheduler.presence_monitor import PresenceMonitor

# 実際の config/ ディレクトリ（safety.yaml などが必要なため）
_REAL_CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "config"


# ──────────────────────────────────────────────
# ヘルパー: スキルレジストリのモック
# ──────────────────────────────────────────────

def _make_skill_registry(*, idle: bool = True) -> dict:
    """
    AgentLoop に渡すモック skill_registry を生成する。

    idle=True の場合、select_skill が常に IDLE を返すため
    Skill 実行をスキップするサイクルが続く（高速テスト向け）。
    """

    async def _build_persona_context(params):
        return {"persona": "test_agent", "tone": "neutral"}

    async def _recall_related(params):
        return []

    async def _select_skill_idle(params):
        return {"selected_skill": "IDLE", "params": {}}

    async def _select_skill_fetch(params):
        return {"selected_skill": "fetch_hacker_news", "params": {"max_items": 1}}

    async def _fetch_hacker_news(params):
        return [{"title": "Test Article", "url": "https://example.com", "content": "stub"}]

    async def _evaluate_importance(params):
        return {"should_store": False, "importance_score": 0.2, "topics": []}

    async def _store_episodic(params):
        return {"stored": True}

    async def _reflect(params):
        return {"summary": "stub reflect"}

    return {
        "build_persona_context": _build_persona_context,
        "recall_related": _recall_related,
        "select_skill": _select_skill_idle if idle else _select_skill_fetch,
        "fetch_hacker_news": _fetch_hacker_news,
        "evaluate_importance": _evaluate_importance,
        "store_episodic": _store_episodic,
        "reflect": _reflect,
    }


# ──────────────────────────────────────────────
# ヘルパー: PresenceMonitor 用モック
# ──────────────────────────────────────────────

async def _mock_maintain_presence(params: dict) -> dict:
    """maintain_presence のモック実装"""
    return {
        "action": "post",
        "platform": "discord",
        "urgency": 0.5,
        "reason": "stub",
    }


# ──────────────────────────────────────────────
# 1. AgentLoop — IDLE サイクル N 回完走
# ──────────────────────────────────────────────

class TestAgentLoopBasicStability:
    """IDLE スキルのみで N サイクル走らせる基本安定性テスト"""

    @pytest.mark.asyncio
    async def test_runs_n_cycles_and_stops(self):
        """3 サイクル正常完了し、is_running が False になること"""
        registry = _make_skill_registry(idle=True)
        loop = AgentLoop(
            character_name="test_agent",
            cycle_interval_seconds=0.0,  # 待機なし
            max_cycles=3,
            config_dir=_REAL_CONFIG_DIR,
            skill_registry=registry,
        )

        await loop.start()

        assert loop.cycle_count == 3
        assert loop.is_running is False

    @pytest.mark.asyncio
    async def test_stop_before_max_cycles(self):
        """stop() 呼び出しで途中終了できること"""
        registry = _make_skill_registry(idle=True)
        loop = AgentLoop(
            character_name="test_agent",
            cycle_interval_seconds=0.05,
            max_cycles=100,
            config_dir=_REAL_CONFIG_DIR,
            skill_registry=registry,
        )

        async def _stopper():
            await asyncio.sleep(0.08)
            await loop.stop()

        await asyncio.gather(loop.start(), _stopper())

        # 強制停止のためサイクル数は 100 未満
        assert loop.cycle_count < 100
        assert loop.is_running is False

    @pytest.mark.asyncio
    async def test_skill_error_does_not_crash_loop(self):
        """Skill 実行中の例外でもループが継続・完走すること"""

        async def _failing_skill(params):
            raise RuntimeError("模擬エラー")

        registry = _make_skill_registry(idle=False)  # fetch_hacker_news を実行させる
        registry["fetch_hacker_news"] = _failing_skill  # 実行時にエラー

        loop = AgentLoop(
            character_name="test_agent",
            cycle_interval_seconds=0.0,
            max_cycles=3,
            config_dir=_REAL_CONFIG_DIR,
            skill_registry=registry,
        )

        # エラーがあってもクラッシュしない
        await loop.start()

        assert loop.cycle_count == 3
        assert loop.is_running is False

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self):
        """start() を 2 回呼んでもエラーにならないこと"""
        registry = _make_skill_registry(idle=True)
        loop = AgentLoop(
            character_name="test_agent",
            cycle_interval_seconds=0.0,
            max_cycles=1,
            config_dir=_REAL_CONFIG_DIR,
            skill_registry=registry,
        )

        await loop.start()
        # 既に停止しているので 2 回目は警告のみ（エラーなし）
        await loop.start()  # 内部で _running=False なので即 start される
        assert loop.cycle_count >= 1


# ──────────────────────────────────────────────
# 2. PresenceMonitor — 単体安定性
# ──────────────────────────────────────────────

class TestPresenceMonitorStability:
    """PresenceMonitor 単体の安定稼働テスト"""

    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        """start() → stop() が正常に完了すること"""
        monitor = PresenceMonitor(
            maintain_presence_fn=_mock_maintain_presence,
            check_interval_seconds=999.0,  # 自動チェックはほぼ発生させない
        )

        await monitor.start()
        assert monitor.is_running is True

        await monitor.stop()
        assert monitor.is_running is False

    @pytest.mark.asyncio
    async def test_check_is_called_at_least_once(self):
        """起動後に少なくとも 1 回 maintain_presence が呼ばれること"""
        calls: list[dict] = []

        async def _counting_fn(params: dict) -> dict:
            calls.append(params)
            return {"action": "idle", "platform": "none", "urgency": 0.0, "reason": "stub"}

        monitor = PresenceMonitor(
            maintain_presence_fn=_counting_fn,
            check_interval_seconds=0.01,  # 10ms ごとにチェック
        )

        await monitor.start()
        await asyncio.sleep(0.05)  # 少なくとも数回実行させる
        await monitor.stop()

        assert len(calls) >= 1, "maintain_presence が 1 度も呼ばれていない"

    @pytest.mark.asyncio
    async def test_activity_timestamps_are_passed(self):
        """record_x_activity() / record_discord_activity() の時刻が params に渡ること"""
        received: list[dict] = []

        async def _capturing_fn(params: dict) -> dict:
            received.append(params)
            return {"action": "idle", "platform": "none", "urgency": 0.0, "reason": "stub"}

        monitor = PresenceMonitor(
            maintain_presence_fn=_capturing_fn,
            check_interval_seconds=999.0,
        )

        monitor.record_x_activity()
        monitor.record_discord_activity()

        # 手動チェック
        result = await monitor._run_check()

        assert len(received) == 1
        params = received[0]
        assert params["last_x_activity_at"] is not None
        assert params["last_discord_activity_at"] is not None
        # ISO 8601 形式であること
        assert "T" in params["last_x_activity_at"]
        assert "T" in params["last_discord_activity_at"]

    @pytest.mark.asyncio
    async def test_maintain_presence_error_does_not_crash_loop(self):
        """maintain_presence が例外を投げてもループが継続すること"""
        call_count = 0

        async def _flaky_fn(params: dict) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("模擬エラー")
            return {"action": "idle", "platform": "none", "urgency": 0.0, "reason": "stub"}

        monitor = PresenceMonitor(
            maintain_presence_fn=_flaky_fn,
            check_interval_seconds=0.01,
        )

        await monitor.start()
        await asyncio.sleep(0.05)
        await monitor.stop()

        # エラー後も継続して複数回呼ばれていること
        assert call_count >= 2


# ──────────────────────────────────────────────
# 3. AgentLoop + PresenceMonitor 協調テスト
# ──────────────────────────────────────────────

class TestAgentLoopWithPresenceMonitor:
    """AgentLoop と PresenceMonitor を同時起動して協調動作を検証する"""

    @pytest.mark.asyncio
    async def test_both_run_concurrently(self):
        """AgentLoop と PresenceMonitor が同時に起動・停止できること"""
        presence_calls: list[int] = []

        async def _counting_presence(params: dict) -> dict:
            presence_calls.append(1)
            return {"action": "idle", "platform": "none", "urgency": 0.0, "reason": "stub"}

        registry = _make_skill_registry(idle=True)
        loop = AgentLoop(
            character_name="test_agent",
            cycle_interval_seconds=0.0,
            max_cycles=5,
            config_dir=_REAL_CONFIG_DIR,
            skill_registry=registry,
        )
        monitor = PresenceMonitor(
            maintain_presence_fn=_counting_presence,
            check_interval_seconds=0.01,
        )

        # 同時起動
        await monitor.start()
        await loop.start()  # max_cycles=5 で完走
        await monitor.stop()

        # AgentLoop が完走し、PresenceMonitor も少なくとも 1 回実行された
        assert loop.cycle_count == 5
        assert loop.is_running is False
        assert monitor.is_running is False
        assert len(presence_calls) >= 1

    @pytest.mark.asyncio
    async def test_cancelled_error_stops_both(self):
        """CancelledError で両コンポーネントが正常終了すること"""
        registry = _make_skill_registry(idle=True)
        loop = AgentLoop(
            character_name="test_agent",
            cycle_interval_seconds=0.05,
            max_cycles=100,
            config_dir=_REAL_CONFIG_DIR,
            skill_registry=registry,
        )
        monitor = PresenceMonitor(
            maintain_presence_fn=_mock_maintain_presence,
            check_interval_seconds=0.05,
        )

        await monitor.start()

        # AgentLoop をタスクとして起動してキャンセル
        task = asyncio.create_task(loop.start())
        await asyncio.sleep(0.1)
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            # main.py のパターン: CancelledError 時に stop() を呼んで _running をリセット
            await loop.stop()

        await monitor.stop()

        # 両方が停止していること
        assert loop.is_running is False
        assert monitor.is_running is False


# ──────────────────────────────────────────────
# 4. キャラクター状態 L3/L4/L5 store → recall 連鎖テスト
# ──────────────────────────────────────────────

class TestCharacterStatePersistence:
    """StoreCharacterState → RecallCharacterState の連鎖テスト（Qdrant モック）"""

    @pytest.mark.asyncio
    async def test_store_and_recall_emotional_state(self):
        """emotional 状態の dry_run 動作と recall が正しいスキーマを返すこと"""
        from skills.memory.store_character_state import StoreCharacterStateSkill
        from skills.memory.recall_character_state import RecallCharacterStateSkill

        store_skill = StoreCharacterStateSkill()
        recall_skill = RecallCharacterStateSkill()

        emotional_state = {
            "joy": 0.7,
            "sadness": 0.1,
            "anger": 0.05,
            "fear": 0.05,
            "surprise": 0.1,
        }

        # dry_run=True は実際には保存しない → stored: False
        store_result = await store_skill.run({
            "character_name": "test_agent",
            "state_type": "emotional",
            "state": emotional_state,
            "dry_run": True,
        })

        assert store_result["stored"] is False
        assert store_result["reason"] == "dry_run"
        assert store_result["character_name"] == "test_agent"
        assert store_result["state_type"] == "emotional"

        # dry_run で recall（保存されていないのでデフォルト応答）
        recall_result = await recall_skill.run({
            "character_name": "test_agent",
            "state_type": "emotional",
            "dry_run": True,
        })

        assert "found" in recall_result
        assert recall_result["character_name"] == "test_agent"
        assert recall_result["state_type"] == "emotional"

    @pytest.mark.asyncio
    async def test_store_all_three_state_types(self):
        """L3/L4/L5 の 3 種類全て dry_run が正しいスキーマを返すこと"""
        from skills.memory.store_character_state import StoreCharacterStateSkill

        store_skill = StoreCharacterStateSkill()

        states = {
            "emotional": {"joy": 0.8, "sadness": 0.1},
            "cognitive": {"focus": 0.9, "load": 0.4},
            "trust": {"discord_user_001": 0.7, "discord_user_002": 0.5},
        }

        for state_type, state_data in states.items():
            result = await store_skill.run({
                "character_name": "test_agent",
                "state_type": state_type,
                "state": state_data,
                "dry_run": True,
            })

            # dry_run は stored=False, reason="dry_run" を返す
            assert result["stored"] is False, f"{state_type} の dry_run が想定外の値"
            assert result["reason"] == "dry_run"
            assert result["state_type"] == state_type
            assert result["character_name"] == "test_agent"

    @pytest.mark.asyncio
    async def test_recall_sequential_states(self):
        """L3→L4→L5 の順に recall を呼び出してもエラーにならないこと（dry_run）"""
        from skills.memory.recall_character_state import RecallCharacterStateSkill

        recall_skill = RecallCharacterStateSkill()

        for state_type in ["emotional", "cognitive", "trust"]:
            result = await recall_skill.run({
                "character_name": "test_agent",
                "state_type": state_type,
                "dry_run": True,
            })

            # dry_run では found=False か found=True のいずれかが返る
            assert "found" in result
            assert result["character_name"] == "test_agent"
            assert result["state_type"] == state_type


# ──────────────────────────────────────────────
# 5. 5サイクル振り返り付き完走テスト
# ──────────────────────────────────────────────

class TestAgentLoopWithReflect:
    """reflect が呼ばれるサイクル数（5の倍数）を含む長めの完走テスト"""

    @pytest.mark.asyncio
    async def test_runs_10_cycles_including_reflect(self):
        """10 サイクル完走し、reflect が 2 回（サイクル 5, 10）呼ばれること"""
        reflect_cycles: list[int] = []
        cycle_counter = 0

        async def _tracking_select_skill(params) -> dict:
            nonlocal cycle_counter
            cycle_counter += 1
            return {"selected_skill": "IDLE", "params": {}}

        async def _tracking_reflect(params) -> dict:
            reflect_cycles.append(cycle_counter)
            return {"summary": f"reflect at cycle {cycle_counter}"}

        registry = _make_skill_registry(idle=True)
        registry["select_skill"] = _tracking_select_skill
        registry["reflect"] = _tracking_reflect

        loop = AgentLoop(
            character_name="test_agent",
            cycle_interval_seconds=0.0,
            max_cycles=10,
            config_dir=_REAL_CONFIG_DIR,
            skill_registry=registry,
        )

        await loop.start()

        assert loop.cycle_count == 10
        # reflect は 5 の倍数サイクル（5, 10）で呼ばれる
        assert len(reflect_cycles) == 2
