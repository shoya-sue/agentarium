"""
tests/test_presence_monitor.py — PresenceMonitor ユニットテスト

プレゼンス監視スケジューラの動作を TDD で検証する。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ---------------------------------------------------------------------------
# TestPresenceMonitorImport
# ---------------------------------------------------------------------------

class TestPresenceMonitorImport:
    """モジュールのインポートを確認する"""

    def test_import(self):
        """scheduler.presence_monitor から PresenceMonitor をインポートできる"""
        from scheduler.presence_monitor import PresenceMonitor
        assert PresenceMonitor is not None


# ---------------------------------------------------------------------------
# TestPresenceMonitorInit
# ---------------------------------------------------------------------------

class TestPresenceMonitorInit:
    """初期化パラメータと初期状態の検証"""

    def test_default_interval(self):
        """デフォルトの check_interval_seconds は 300 秒（5分）"""
        from scheduler.presence_monitor import PresenceMonitor

        mock_fn = AsyncMock(return_value={"action": "idle", "platform": "none", "urgency": 0.0})
        monitor = PresenceMonitor(maintain_presence_fn=mock_fn)
        assert monitor.check_interval_seconds == 300.0

    def test_custom_interval(self):
        """カスタムインターバルを設定できる"""
        from scheduler.presence_monitor import PresenceMonitor

        mock_fn = AsyncMock(return_value={"action": "idle", "platform": "none", "urgency": 0.0})
        monitor = PresenceMonitor(maintain_presence_fn=mock_fn, check_interval_seconds=60.0)
        assert monitor.check_interval_seconds == 60.0

    def test_initial_state_not_running(self):
        """初期状態では is_running が False"""
        from scheduler.presence_monitor import PresenceMonitor

        mock_fn = AsyncMock(return_value={"action": "idle", "platform": "none", "urgency": 0.0})
        monitor = PresenceMonitor(maintain_presence_fn=mock_fn)
        assert monitor.is_running is False


# ---------------------------------------------------------------------------
# TestPresenceMonitorStart
# ---------------------------------------------------------------------------

class TestPresenceMonitorStart:
    """start / stop の状態遷移を検証する"""

    def test_start_sets_running(self):
        """start() 後に is_running が True になる"""
        from scheduler.presence_monitor import PresenceMonitor

        mock_fn = AsyncMock(return_value={"action": "idle", "platform": "none", "urgency": 0.0})
        monitor = PresenceMonitor(maintain_presence_fn=mock_fn, check_interval_seconds=9999.0)

        async def _run():
            await monitor.start()
            assert monitor.is_running is True
            await monitor.stop()

        asyncio.run(_run())

    def test_stop_sets_not_running(self):
        """start() → stop() 後に is_running が False になる"""
        from scheduler.presence_monitor import PresenceMonitor

        mock_fn = AsyncMock(return_value={"action": "idle", "platform": "none", "urgency": 0.0})
        monitor = PresenceMonitor(maintain_presence_fn=mock_fn, check_interval_seconds=9999.0)

        async def _run():
            await monitor.start()
            await monitor.stop()
            assert monitor.is_running is False

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# TestPresenceMonitorCycle
# ---------------------------------------------------------------------------

class TestPresenceMonitorCycle:
    """_run_check() の動作を検証する"""

    def test_cycle_calls_maintain_presence(self):
        """_run_check() が maintain_presence 関数を呼び出す"""
        from scheduler.presence_monitor import PresenceMonitor

        mock_fn = AsyncMock(return_value={"action": "discord_monitor", "platform": "discord", "urgency": 0.5})
        monitor = PresenceMonitor(maintain_presence_fn=mock_fn)

        async def _run():
            await monitor._run_check()
            mock_fn.assert_called_once()
            # 呼び出し引数に必要なキーが含まれている
            call_kwargs = mock_fn.call_args[0][0]
            assert "last_x_activity_at" in call_kwargs
            assert "last_discord_activity_at" in call_kwargs
            assert "fatigue" in call_kwargs

        asyncio.run(_run())

    def test_cycle_updates_last_action(self):
        """_run_check() 後に last_action が更新される"""
        from scheduler.presence_monitor import PresenceMonitor

        mock_fn = AsyncMock(return_value={"action": "x_browse", "platform": "x", "urgency": 0.3})
        monitor = PresenceMonitor(maintain_presence_fn=mock_fn)

        async def _run():
            await monitor._run_check()
            assert monitor.last_action == "x_browse"

        asyncio.run(_run())

    def test_cycle_with_none_fatigue(self):
        """fatigue を省略した場合、デフォルト 0.0 で呼び出される"""
        from scheduler.presence_monitor import PresenceMonitor

        mock_fn = AsyncMock(return_value={"action": "idle", "platform": "none", "urgency": 0.0})
        monitor = PresenceMonitor(maintain_presence_fn=mock_fn)

        async def _run():
            await monitor._run_check()  # fatigue 指定なし
            call_kwargs = mock_fn.call_args[0][0]
            assert call_kwargs["fatigue"] == 0.0

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# TestPresenceMonitorActivityUpdate
# ---------------------------------------------------------------------------

class TestPresenceMonitorActivityUpdate:
    """アクティビティ記録メソッドを検証する"""

    def test_update_x_activity(self):
        """record_x_activity() が内部タイムスタンプを更新する"""
        from scheduler.presence_monitor import PresenceMonitor

        mock_fn = AsyncMock(return_value={"action": "idle", "platform": "none", "urgency": 0.0})
        monitor = PresenceMonitor(maintain_presence_fn=mock_fn)

        before = monitor._last_x_activity_at
        monitor.record_x_activity()
        after = monitor._last_x_activity_at

        assert after is not None
        assert after != before

    def test_update_discord_activity(self):
        """record_discord_activity() が内部タイムスタンプを更新する"""
        from scheduler.presence_monitor import PresenceMonitor

        mock_fn = AsyncMock(return_value={"action": "idle", "platform": "none", "urgency": 0.0})
        monitor = PresenceMonitor(maintain_presence_fn=mock_fn)

        before = monitor._last_discord_activity_at
        monitor.record_discord_activity()
        after = monitor._last_discord_activity_at

        assert after is not None
        assert after != before

    def test_last_action_initially_none(self):
        """チェック実行前は last_action が None"""
        from scheduler.presence_monitor import PresenceMonitor

        mock_fn = AsyncMock(return_value={"action": "idle", "platform": "none", "urgency": 0.0})
        monitor = PresenceMonitor(maintain_presence_fn=mock_fn)

        assert monitor.last_action is None
