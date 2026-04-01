"""
skills/character/maintain_presence.py — X / Discord プレゼンス維持 Skill

最後の活動時刻と疲労度から、次に取るべきプレゼンス行動を推奨する。
LLM 不要のルールベース意思決定 Skill。

設計根拠: docs/1_plan.md — Section 10 常時存在（X + Discord デュアルプレゼンス）
Skill 入出力スキーマ: config/skills/character/maintain_presence.yaml
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# プラットフォーム別の活動間隔閾値（分）
_DISCORD_INTERVAL_MIN: int = 15
_X_INTERVAL_MIN: int = 30

# activity が None の場合に使う「非常に昔」の経過時間（分）
_NULL_ELAPSED_MIN: float = 9999.0

# 有効なアクション一覧
VALID_ACTIONS: frozenset[str] = frozenset({
    "discord_monitor",      # Discord チャンネル監視
    "discord_respond",      # Discord メンション応答
    "x_browse",             # X タイムライン閲覧
    "idle",                 # 活動不要
})


def _parse_iso(dt_str: str | None) -> datetime | None:
    """ISO 8601 文字列を timezone-aware datetime にパースする。"""
    if dt_str is None:
        return None
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _elapsed_minutes(last_at: str | None, now: datetime) -> float:
    """最後の活動時刻から現在までの経過時間（分）を返す。"""
    dt = _parse_iso(last_at)
    if dt is None:
        return _NULL_ELAPSED_MIN
    delta = now - dt
    return max(0.0, delta.total_seconds() / 60.0)


def _compute_urgency(
    discord_elapsed: float,
    x_elapsed: float,
    fatigue: float,
) -> float:
    """
    urgency（0.0〜1.0）を計算する。

    疲労度が高いほど urgency を低減する（疲労時は休む）。
    """
    discord_ratio = discord_elapsed / _DISCORD_INTERVAL_MIN
    x_ratio = x_elapsed / _X_INTERVAL_MIN
    base_urgency = min(1.0, max(discord_ratio, x_ratio) / 3.0)

    # 疲労が高いほど urgency を抑制（最大 50% 抑制）
    fatigue_factor = 1.0 - 0.5 * max(0.0, min(1.0, fatigue))
    return round(base_urgency * fatigue_factor, 4)


class MaintainPresenceSkill:
    """
    maintain_presence Skill の実装。

    最後の活動時刻と疲労度から、次に取るべきプレゼンス行動を推奨する。
    Discord（15分間隔）→ X（30分間隔）の優先順で判定する。
    """

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        プレゼンス行動を推奨する。

        Args:
            params:
                last_x_activity_at (str | None): 最後の X 活動時刻（ISO 8601）
                last_discord_activity_at (str | None): 最後の Discord 活動時刻（ISO 8601）
                fatigue (float | None): 現在の疲労度 0.0〜1.0（省略時: 0.0）

        Returns:
            {
                "action": str,      # 推奨アクション（VALID_ACTIONS のいずれか）
                "platform": str,    # 対象プラットフォーム（x / discord / none）
                "urgency": float,   # 緊急度 0.0〜1.0
            }
        """
        last_x: str | None = params.get("last_x_activity_at")
        last_discord: str | None = params.get("last_discord_activity_at")
        fatigue: float = float(params.get("fatigue") or 0.0)

        now = datetime.now(timezone.utc)
        discord_elapsed = _elapsed_minutes(last_discord, now)
        x_elapsed = _elapsed_minutes(last_x, now)

        urgency = _compute_urgency(discord_elapsed, x_elapsed, fatigue)

        # 意思決定: Discord → X → idle の順で評価
        discord_overdue = discord_elapsed >= _DISCORD_INTERVAL_MIN
        x_overdue = x_elapsed >= _X_INTERVAL_MIN

        if discord_overdue and x_overdue:
            # 両方期限超過: より超過度が大きい方を優先
            discord_ratio = discord_elapsed / _DISCORD_INTERVAL_MIN
            x_ratio = x_elapsed / _X_INTERVAL_MIN
            if discord_ratio >= x_ratio:
                action, platform = "discord_monitor", "discord"
            else:
                action, platform = "x_browse", "x"
        elif discord_overdue:
            action, platform = "discord_monitor", "discord"
        elif x_overdue:
            action, platform = "x_browse", "x"
        else:
            action, platform = "idle", "none"

        logger.debug(
            "maintain_presence: action=%s platform=%s urgency=%.3f "
            "discord_elapsed=%.1fm x_elapsed=%.1fm fatigue=%.2f",
            action,
            platform,
            urgency,
            discord_elapsed,
            x_elapsed,
            fatigue,
        )

        return {
            "action": action,
            "platform": platform,
            "urgency": urgency,
        }
