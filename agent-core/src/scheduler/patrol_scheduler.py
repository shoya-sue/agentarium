"""
scheduler/patrol_scheduler.py — ルールベース巡回スケジューラ

config/schedules/patrol.yaml に従い、各情報ソースを定期的に巡回する。

動作仕様:
  - run_all_on_startup: true の場合、起動時に全有効ソースを1回実行
  - 各ソースは interval_min ごとに実行
  - max_concurrent: 1（ブラウザ共有のため逐次実行）
  - retry_on_failure: true / retry_delay_sec: 60 / max_retries: 2
  - active_hours (JST 07:00〜01:00) 範囲外は巡回しない
  - priority_order に従って実行順序を決定

Usage:
    scheduler = PatrolScheduler(config_dir=Path("config"))
    await scheduler.start()     # バックグラウンドループ開始
    await scheduler.stop()      # 停止
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Callable, Awaitable

from zoneinfo import ZoneInfo

from utils.config import load_yaml_config

logger = logging.getLogger(__name__)

# 日本時間タイムゾーン
_JST = ZoneInfo("Asia/Tokyo")

# デフォルト設定値
_DEFAULT_INTERVAL_MIN = 60
_DEFAULT_MAX_RETRIES = 2
_DEFAULT_RETRY_DELAY_SEC = 60
_DEFAULT_MAX_CONCURRENT = 1

# ポーリング間隔（メインループのスリープ秒数）
_POLL_INTERVAL_SEC = 30


@dataclass
class SourceState:
    """各ソースの実行状態を保持する不変スナップショット。"""

    source_id: str
    interval_min: int
    enabled: bool
    last_run_at: datetime | None = None
    consecutive_failures: int = 0

    def with_last_run(self, ts: datetime) -> "SourceState":
        """last_run_at を更新した新しいインスタンスを返す。"""
        return SourceState(
            source_id=self.source_id,
            interval_min=self.interval_min,
            enabled=self.enabled,
            last_run_at=ts,
            consecutive_failures=0,
        )

    def with_failure(self) -> "SourceState":
        """連続失敗数をインクリメントした新しいインスタンスを返す。"""
        return SourceState(
            source_id=self.source_id,
            interval_min=self.interval_min,
            enabled=self.enabled,
            last_run_at=self.last_run_at,
            consecutive_failures=self.consecutive_failures + 1,
        )

    def is_due(self, now: datetime) -> bool:
        """次回実行タイミングに達しているか判定する。"""
        if not self.enabled:
            return False
        if self.last_run_at is None:
            return True
        elapsed_min = (now - self.last_run_at).total_seconds() / 60
        return elapsed_min >= self.interval_min


# 巡回ハンドラの型エイリアス
# source_id を受け取り、収集結果 list[dict] を返す非同期関数
PatrolHandler = Callable[[str], Awaitable[list[dict[str, Any]]]]


class PatrolScheduler:
    """
    ルールベース巡回スケジューラ。

    patrol.yaml の設定に従って各情報ソースを定期実行し、
    登録されたハンドラに source_id を渡す。

    Args:
        config_dir: config/ ディレクトリのパス
        handler: source_id を受け取る非同期コールバック
                 省略時は _default_handler（ログ出力のみ）を使用
    """

    def __init__(
        self,
        config_dir: Path | str,
        handler: PatrolHandler | None = None,
    ) -> None:
        self._config_dir = Path(config_dir)
        self._schedule_yaml = self._config_dir / "schedules" / "patrol.yaml"
        self._handler: PatrolHandler = handler or _default_handler

        # 実行状態マップ: source_id → SourceState（不変更新パターン）
        self._states: dict[str, SourceState] = {}

        # スケジューラ設定
        self._scheduler_cfg: dict[str, Any] = {}

        # 実行中フラグ
        self._running = False
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """スケジューラのバックグラウンドループを開始する。"""
        if self._running:
            logger.warning("PatrolScheduler は既に起動中です")
            return

        self._load_config()
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="patrol_scheduler")
        logger.info("PatrolScheduler 開始")

    async def stop(self) -> None:
        """スケジューラを停止する。"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("PatrolScheduler 停止")

    def get_states(self) -> dict[str, SourceState]:
        """現在のソース状態のコピーを返す（読み取り専用）。"""
        return dict(self._states)

    # ------------------------------------------------------------------
    # 設定読み込み
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        """patrol.yaml を読み込み、ソース状態を初期化する。"""
        config = load_yaml_config(self._schedule_yaml)
        self._scheduler_cfg = config.get("scheduler", {})
        patrol_entries: list[dict[str, Any]] = config.get("patrol", [])

        # 優先度順に並び替えるためのインデックスを構築
        priority_order: list[str] = self._scheduler_cfg.get("priority_order", [])
        priority_index: dict[str, int] = {
            src: idx for idx, src in enumerate(priority_order)
        }

        sorted_entries = sorted(
            patrol_entries,
            key=lambda e: priority_index.get(e.get("source", ""), 9999),
        )

        # SourceState を初期化（既存の状態は保持）
        new_states: dict[str, SourceState] = {}
        for entry in sorted_entries:
            source_id: str = entry.get("source", "")
            if not source_id:
                continue

            existing = self._states.get(source_id)
            new_states[source_id] = SourceState(
                source_id=source_id,
                interval_min=int(entry.get("interval_min", _DEFAULT_INTERVAL_MIN)),
                enabled=bool(entry.get("enabled", True)),
                last_run_at=existing.last_run_at if existing else None,
                consecutive_failures=existing.consecutive_failures if existing else 0,
            )

        self._states = new_states
        logger.info(
            "PatrolScheduler 設定読み込み: %d ソース（有効: %d）",
            len(self._states),
            sum(1 for s in self._states.values() if s.enabled),
        )

    # ------------------------------------------------------------------
    # メインループ
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """巡回メインループ。"""
        run_on_startup = self._scheduler_cfg.get("run_all_on_startup", True)

        if run_on_startup:
            logger.info("起動時一括巡回を開始します")
            await self._run_all_enabled()

        while self._running:
            await asyncio.sleep(_POLL_INTERVAL_SEC)

            if not self._is_active_hour():
                logger.debug("非活動時間帯のためスキップ")
                continue

            now = datetime.now(timezone.utc)
            due_sources = [
                state
                for state in self._states.values()
                if state.is_due(now)
            ]

            for state in due_sources:
                if not self._running:
                    break
                await self._run_source(state)

    async def _run_all_enabled(self) -> None:
        """有効な全ソースを順番に1回実行する（起動時処理）。"""
        for state in self._states.values():
            if not state.enabled:
                continue
            if not self._running:
                break
            await self._run_source(state)

    async def _run_source(self, state: SourceState) -> None:
        """
        単一ソースを実行する。失敗時はリトライを行う。

        状態は不変パターンで更新する（新インスタンスで置き換え）。
        """
        max_retries: int = self._scheduler_cfg.get("max_retries", _DEFAULT_MAX_RETRIES)
        retry_delay_sec: int = int(
            self._scheduler_cfg.get("retry_delay_sec", _DEFAULT_RETRY_DELAY_SEC)
        )
        retry_on_failure: bool = self._scheduler_cfg.get("retry_on_failure", True)

        source_id = state.source_id
        attempt = 0

        while attempt <= max_retries:
            try:
                logger.info(
                    "ソース巡回開始: %s（試行 %d/%d）",
                    source_id,
                    attempt + 1,
                    max_retries + 1,
                )
                items = await self._handler(source_id)
                now = datetime.now(timezone.utc)
                self._states[source_id] = self._states[source_id].with_last_run(now)
                logger.info(
                    "ソース巡回完了: %s — %d 件取得",
                    source_id,
                    len(items) if items else 0,
                )
                return

            except Exception as exc:
                attempt += 1
                logger.warning(
                    "ソース巡回失敗: %s — %s（試行 %d/%d）",
                    source_id,
                    exc,
                    attempt,
                    max_retries + 1,
                )
                self._states[source_id] = self._states[source_id].with_failure()

                if not retry_on_failure or attempt > max_retries:
                    logger.error(
                        "ソース巡回中止: %s — 最大リトライ回数に達しました",
                        source_id,
                    )
                    return

                logger.info(
                    "リトライ待機: %d 秒後に再試行 (%s)",
                    retry_delay_sec,
                    source_id,
                )
                await asyncio.sleep(retry_delay_sec)

    # ------------------------------------------------------------------
    # 活動時間帯チェック
    # ------------------------------------------------------------------

    def _is_active_hour(self) -> bool:
        """
        現在時刻が active_hours（JST）範囲内かどうかを判定する。

        active_hours が未設定の場合は常に True を返す。
        start > end（深夜をまたぐ範囲）にも対応する。
        例: start="07:00", end="01:00" → 07:00〜翌01:00が活動時間
        """
        active_hours: list[dict[str, str]] = self._scheduler_cfg.get("active_hours", [])
        if not active_hours:
            return True

        now_jst = datetime.now(_JST).time()

        for window in active_hours:
            start_str: str = window.get("start", "00:00")
            end_str: str = window.get("end", "23:59")

            start_t = _parse_time(start_str)
            end_t = _parse_time(end_str)

            if start_t <= end_t:
                # 通常範囲: 例 09:00 〜 17:00
                if start_t <= now_jst <= end_t:
                    return True
            else:
                # 深夜をまたぐ範囲: 例 07:00 〜 01:00
                # now が start 以降、または end 以前
                if now_jst >= start_t or now_jst <= end_t:
                    return True

        return False


# ------------------------------------------------------------------
# ユーティリティ
# ------------------------------------------------------------------


def _parse_time(time_str: str) -> time:
    """
    "HH:MM" 形式の文字列を datetime.time に変換する。

    不正な形式の場合は midnight (00:00) を返す。
    """
    try:
        parts = time_str.split(":")
        return time(int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        logger.warning("時刻解析失敗: '%s'。00:00 として扱います", time_str)
        return time(0, 0)


async def _default_handler(source_id: str) -> list[dict[str, Any]]:
    """
    デフォルトハンドラ（テスト・デバッグ用）。

    実際の巡回はこのハンドラの代わりに BrowseSourceSkill.run を使用する。
    """
    logger.info("[default_handler] source_id=%s — 実装なし（スキップ）", source_id)
    return []
