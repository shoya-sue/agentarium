"""
scheduler/presence_monitor.py — プレゼンス監視スケジューラ

MaintainPresenceSkill を定期的に呼び出し、X / Discord のプレゼンス行動を推奨する。
アクティビティ記録メソッドで最終活動時刻を更新できる。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Any

logger = logging.getLogger(__name__)


class PresenceMonitor:
    """
    プレゼンス監視スケジューラ。

    check_interval_seconds ごとに maintain_presence_fn を呼び出し、
    推奨アクションを取得する。

    Args:
        maintain_presence_fn: MaintainPresenceSkill.run 相当の非同期呼び出し可能オブジェクト
        check_interval_seconds: チェック間隔（秒）。デフォルト 300 秒（5分）
    """

    def __init__(
        self,
        maintain_presence_fn: Callable,
        check_interval_seconds: float = 300.0,
    ) -> None:
        self._maintain_presence_fn = maintain_presence_fn
        self.check_interval_seconds = check_interval_seconds

        # 各プラットフォームの最終活動時刻（datetime または None）
        self._last_x_activity_at: datetime | None = None
        self._last_discord_activity_at: datetime | None = None

        # 最後のチェック結果
        self._last_result: dict[str, Any] | None = None

        # バックグラウンドタスク管理
        self._running = False
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # プロパティ
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """バックグラウンドループが稼働中かどうか"""
        return self._running

    @property
    def last_action(self) -> str | None:
        """最後のチェックで推奨されたアクション。チェック未実行時は None"""
        if self._last_result is None:
            return None
        return self._last_result.get("action")

    # ------------------------------------------------------------------
    # アクティビティ記録
    # ------------------------------------------------------------------

    def record_x_activity(self) -> None:
        """X でアクティビティが発生した時刻を記録する"""
        self._last_x_activity_at = datetime.now(timezone.utc)
        logger.debug("X アクティビティを記録: %s", self._last_x_activity_at.isoformat())

    def record_discord_activity(self) -> None:
        """Discord でアクティビティが発生した時刻を記録する"""
        self._last_discord_activity_at = datetime.now(timezone.utc)
        logger.debug("Discord アクティビティを記録: %s", self._last_discord_activity_at.isoformat())

    # ------------------------------------------------------------------
    # チェック実行
    # ------------------------------------------------------------------

    async def _run_check(self, fatigue: float = 0.0) -> dict[str, Any]:
        """
        1 回のプレゼンスチェックを実行し結果を返す。

        Args:
            fatigue: 現在の疲労度 0.0〜1.0（省略時: 0.0）

        Returns:
            maintain_presence_fn の戻り値（action, platform, urgency を含む dict）
        """
        # datetime を ISO 8601 文字列に変換（None はそのまま渡す）
        last_x_iso = (
            self._last_x_activity_at.isoformat()
            if self._last_x_activity_at is not None
            else None
        )
        last_discord_iso = (
            self._last_discord_activity_at.isoformat()
            if self._last_discord_activity_at is not None
            else None
        )

        params = {
            "last_x_activity_at": last_x_iso,
            "last_discord_activity_at": last_discord_iso,
            "fatigue": fatigue,
        }

        result: dict[str, Any] = await self._maintain_presence_fn(params)
        self._last_result = result

        logger.debug(
            "presence_monitor チェック完了: action=%s urgency=%.3f",
            result.get("action"),
            result.get("urgency", 0.0),
        )
        return result

    # ------------------------------------------------------------------
    # ループ制御
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """チェックループを開始する（非ブロッキング — バックグラウンドタスク起動）"""
        if self._running:
            logger.warning("PresenceMonitor は既に起動中です")
            return

        self._running = True
        self._task = asyncio.create_task(self._loop(), name="presence_monitor")
        logger.info("PresenceMonitor 開始（interval=%.0fs）", self.check_interval_seconds)

    async def stop(self) -> None:
        """チェックループを停止する"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("PresenceMonitor 停止")

    async def _loop(self) -> None:
        """チェックメインループ"""
        while self._running:
            try:
                await self._run_check()
            except Exception as exc:
                logger.warning("presence_monitor チェック失敗: %s", exc)
            await asyncio.sleep(self.check_interval_seconds)
