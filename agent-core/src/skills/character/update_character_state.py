"""
skills/character/update_character_state.py — L4 Cognitive State 更新 Skill

Skill 実行トリガーや時間経過をもとに、L4 Cognitive State
（cognitive_load / fatigue / focus）をルールベースで更新する。
LLM 不要の純粋計算 Skill。

設計根拠: docs/5_character_framework.md — L4 Cognitive State
Skill 入出力スキーマ: config/skills/character/update_character_state.yaml
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# 値の範囲
_SCORE_MIN: float = 0.0
_SCORE_MAX: float = 1.0

# topic_switch 時の focus リセット値
_FOCUS_RESET: float = 0.3

# 疲労蓄積レート（1時間あたり）
_FATIGUE_ACCUMULATION_PER_HOUR: float = 0.04

# トリガー別の固定 delta（設計書より）
_TRIGGER_DELTAS: dict[str, dict[str, float]] = {
    "skill_execution": {
        "cognitive_load": +0.05,
        "fatigue": +0.02,
    },
    "llm_heavy_task": {
        "cognitive_load": +0.15,
        "focus": +0.1,
    },
    "idle_period": {
        "cognitive_load": -0.1,
        "fatigue": -0.05,
        "focus": -0.1,
    },
}

# topic_switch は focus をリセットする特殊トリガー
_TOPIC_SWITCH_TRIGGER = "topic_switch"


def _clamp(value: float) -> float:
    """値を 0.0〜1.0 の範囲に収める。"""
    return max(_SCORE_MIN, min(_SCORE_MAX, value))


def _apply_trigger(
    state: dict[str, float],
    trigger: str,
) -> dict[str, float]:
    """
    トリガーに基づいて状態を更新する（イミュータブル）。

    topic_switch は focus を FOCUS_RESET にリセットする。
    その他のトリガーは固定 delta を適用する。
    """
    new_state = dict(state)

    if trigger == _TOPIC_SWITCH_TRIGGER:
        new_state["focus"] = _FOCUS_RESET
        return new_state

    delta = _TRIGGER_DELTAS.get(trigger)
    if delta is None:
        logger.warning("update_character_state: 未知のトリガー '%s' は無視します", trigger)
        return new_state

    for field, amount in delta.items():
        current = new_state.get(field, 0.0)
        new_state[field] = _clamp(current + amount)

    return new_state


def _apply_time_fatigue(
    state: dict[str, float],
    elapsed_hours: float,
) -> dict[str, float]:
    """
    時間経過による疲労蓄積を適用する（イミュータブル）。

    elapsed_hours == 0 の場合は変化なし。
    """
    if elapsed_hours <= 0.0:
        return dict(state)

    new_state = dict(state)
    fatigue_increase = _FATIGUE_ACCUMULATION_PER_HOUR * elapsed_hours
    current_fatigue = new_state.get("fatigue", 0.0)
    new_state["fatigue"] = _clamp(current_fatigue + fatigue_increase)
    return new_state


class UpdateCharacterStateSkill:
    """
    update_character_state Skill の実装。

    L4 Cognitive State（cognitive_load / fatigue / focus）を
    トリガーと時間経過にもとづいてルールベースで更新する。
    """

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        L4 Cognitive State を更新する。

        Args:
            params:
                character (str): キャラクター名（必須）
                current_state (dict): 現在の認知状態（必須）
                    cognitive_load (float): 認知負荷 0.0〜1.0
                    fatigue (float): 疲労度 0.0〜1.0
                    focus (float): 集中度 0.0〜1.0
                trigger (str | None): トリガー名
                    skill_execution / llm_heavy_task / idle_period / topic_switch
                elapsed_hours (float | None): 経過時間（疲労蓄積計算用、省略時: 0.0）

        Returns:
            {
                "character": str,
                "state": dict[str, float],  # 更新後の認知状態
                "updated_at": str,           # ISO 8601 タイムスタンプ
            }
        """
        character: str = params["character"]
        current_state: dict[str, float] = dict(params.get("current_state") or {})
        trigger: str | None = params.get("trigger")
        elapsed_hours: float = float(params.get("elapsed_hours") or 0.0)

        state = current_state

        # 1. トリガー適用
        if trigger:
            state = _apply_trigger(state, trigger)

        # 2. 時間経過による疲労蓄積
        state = _apply_time_fatigue(state, elapsed_hours)

        updated_at = datetime.now(timezone.utc).isoformat()

        logger.debug(
            "update_character_state: character=%s trigger=%s elapsed_hours=%.2f "
            "cognitive_load=%.2f fatigue=%.2f focus=%.2f",
            character,
            trigger,
            elapsed_hours,
            state.get("cognitive_load", 0.0),
            state.get("fatigue", 0.0),
            state.get("focus", 0.0),
        )

        return {
            "character": character,
            "state": state,
            "updated_at": updated_at,
        }
