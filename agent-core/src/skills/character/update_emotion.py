"""
skills/character/update_emotion.py — ルールベース感情状態更新 Skill

Skill 実行トリガーや明示的な delta を受け取り、キャラクターの感情状態を
ルールベースで更新する（LLM 不要）。
時間経過による中立点への減衰も適用する。

設計根拠: docs/5_character_framework.md — L3 Emotional State
Skill 入出力スキーマ: config/skills/character/update_emotion.yaml
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# 感情値の範囲
_SCORE_MIN: float = 0.0
_SCORE_MAX: float = 1.0

# 中立点
NEUTRAL_POINT: float = 0.5

# 1時間あたりの減衰量（中立点方向へ）
DECAY_RATE_PER_HOUR: float = 0.1

# Skill 実行トリガー別の固定 delta（設計書より）
_TRIGGER_DELTAS: dict[str, dict[str, float]] = {
    "skill_success": {
        "satisfaction": +0.1,
        "frustration": -0.05,
        "pride": +0.05,
    },
    "skill_failure": {
        "frustration": +0.15,
        "satisfaction": -0.05,
        "anxiety": +0.05,
    },
    "user_interaction": {
        "satisfaction": +0.1,
        "boredom": -0.1,
    },
}


def _clamp(value: float) -> float:
    """感情値を 0.0〜1.0 の範囲に収める。"""
    return max(_SCORE_MIN, min(_SCORE_MAX, value))


def _apply_delta(
    state: dict[str, float],
    delta: dict[str, float],
) -> dict[str, float]:
    """
    delta を state に適用する（イミュータブル）。

    current_state に存在しない軸の delta は無視する。
    """
    new_state = dict(state)
    for axis, amount in delta.items():
        if axis not in new_state:
            continue
        new_state[axis] = _clamp(new_state[axis] + amount)
    return new_state


def _apply_decay(
    state: dict[str, float],
    elapsed_hours: float,
) -> dict[str, float]:
    """
    時間経過による減衰を適用する（中立点 0.5 方向へ）。

    各軸の値が中立点より高ければ減少、低ければ増加する。
    elapsed_hours == 0 の場合は変化なし。
    """
    if elapsed_hours <= 0.0:
        return dict(state)

    decay_amount = DECAY_RATE_PER_HOUR * elapsed_hours
    new_state: dict[str, float] = {}
    for axis, value in state.items():
        if value > NEUTRAL_POINT:
            new_value = max(NEUTRAL_POINT, value - decay_amount)
        elif value < NEUTRAL_POINT:
            new_value = min(NEUTRAL_POINT, value + decay_amount)
        else:
            new_value = value
        new_state[axis] = new_value
    return new_state


class UpdateEmotionSkill:
    """
    update_emotion Skill の実装（ルールベース）。

    trigger または明示的な delta を受け取り、感情状態を更新する。
    時間経過による中立点への減衰も適用する。
    """

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        感情状態をルールベースで更新する。

        Args:
            params:
                character (str): キャラクター名（必須）
                current_state (dict[str, float]): 現在の感情状態（必須）
                delta (dict[str, float] | None): 明示的な delta（省略可）
                trigger (str | None): Skill トリガー名（skill_success / skill_failure / user_interaction）
                elapsed_hours (float | None): 経過時間（省略時: 0.0）

        Returns:
            {
                "character": str,
                "state": dict[str, float],  # 更新後の感情状態
                "updated_at": str,           # ISO 8601 タイムスタンプ
            }
        """
        character: str = params["character"]
        current_state: dict[str, float] = dict(params["current_state"])
        explicit_delta: dict[str, float] = params.get("delta") or {}
        trigger: str | None = params.get("trigger")
        elapsed_hours: float = float(params.get("elapsed_hours") or 0.0)

        state = current_state

        # 1. trigger による固定 delta を適用
        if trigger and trigger in _TRIGGER_DELTAS:
            state = _apply_delta(state, _TRIGGER_DELTAS[trigger])
        elif trigger:
            logger.warning("update_emotion: 未知のトリガー '%s' は無視します", trigger)

        # 2. 明示的な delta を適用
        if explicit_delta:
            state = _apply_delta(state, explicit_delta)

        # 3. 時間経過による減衰を適用
        state = _apply_decay(state, elapsed_hours)

        updated_at = datetime.now(timezone.utc).isoformat()

        logger.debug(
            "update_emotion: character=%s trigger=%s elapsed_hours=%.2f",
            character,
            trigger,
            elapsed_hours,
        )

        return {
            "character": character,
            "state": state,
            "updated_at": updated_at,
        }
