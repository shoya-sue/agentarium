"""
skills/character/apply_drift.py — Big Five パーソナリティドリフト Skill

体験イベントにもとづいて Big Five パーソナリティ値を微小変化させる。
LLM 不要の純粋計算 Skill。

設計根拠: docs/5_character_framework.md — Big Five Drift
Skill 入出力スキーマ: config/skills/character/apply_drift.yaml

制約:
  - max_drift_per_month: 月あたりの最大変化量（例: 0.05）
  - max_cumulative_drift: ベースラインからの最大累積ズレ（例: 0.20）
  - 各値は 0.0〜1.0 の範囲に収める
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Big Five 5特性名
_BIG_FIVE_TRAITS: tuple[str, ...] = (
    "openness",
    "conscientiousness",
    "extraversion",
    "agreeableness",
    "neuroticism",
)

# 値の範囲
_SCORE_MIN: float = 0.0
_SCORE_MAX: float = 1.0

# 1ヶ月を日数で近似（30日）
_DAYS_PER_MONTH: float = 30.0

# イベントタイプ別のドリフト定義
# キー: イベントタイプ, 値: {特性: 1回あたりの変化量}
# 変化量は intensity (0.0〜1.0) をスケーリングして適用する
_EVENT_DRIFT_MAP: dict[str, dict[str, float]] = {
    # Zephyr 向け
    "repeated_success": {
        "conscientiousness": +0.010,
        "openness": +0.005,
    },
    "novel_discoveries": {
        "openness": +0.020,
        "extraversion": +0.005,
    },
    "social_interactions": {
        "extraversion": +0.010,
        "agreeableness": +0.008,
    },
    "negative_experiences": {
        "agreeableness": -0.008,
        "neuroticism": +0.010,
    },
    # Lynx 向け
    "validated_predictions": {
        "conscientiousness": +0.012,
        "neuroticism": -0.005,
    },
    "disproved_hypotheses": {
        "openness": +0.008,
        "conscientiousness": -0.005,
    },
    "high_stakes_errors": {
        "neuroticism": +0.012,
        "conscientiousness": +0.015,
    },
}


def _clamp(value: float) -> float:
    """値を 0.0〜1.0 の範囲に収める（イミュータブル）。"""
    return max(_SCORE_MIN, min(_SCORE_MAX, value))


def _apply_cumulative_cap(
    trait: str,
    new_value: float,
    baseline: float,
    max_cumulative_drift: float,
) -> float:
    """
    累積ドリフト上限を超えないようにクランプする（イミュータブル）。

    baseline ± max_cumulative_drift の範囲に収める。
    """
    lower = _clamp(baseline - max_cumulative_drift)
    upper = _clamp(baseline + max_cumulative_drift)
    return max(lower, min(upper, new_value))


def _calculate_per_event_drift(
    current: dict[str, float],
    baseline: dict[str, float],
    events: list[dict[str, Any]],
    max_cumulative_drift: float,
) -> tuple[dict[str, float], dict[str, float]]:
    """
    イベントリストに基づいてドリフトを計算する（イミュータブル）。

    Args:
        current: 現在の Big Five 値
        baseline: 初期（ベースライン）Big Five 値
        events: イベントリスト。各 dict は {type: str, intensity: float} を含む
        max_cumulative_drift: ベースラインからの最大累積ズレ

    Returns:
        (updated_values, delta_per_trait)
    """
    result = dict(current)
    delta: dict[str, float] = {t: 0.0 for t in _BIG_FIVE_TRAITS}

    for event in events:
        event_type: str = event.get("type", "")
        intensity: float = float(event.get("intensity", 1.0))
        # intensity は 0.0〜1.0 にクランプ
        intensity = max(0.0, min(1.0, intensity))

        trait_deltas = _EVENT_DRIFT_MAP.get(event_type)
        if trait_deltas is None:
            logger.warning("apply_drift: 未知のイベントタイプ '%s' を無視します", event_type)
            continue

        for trait, base_delta in trait_deltas.items():
            if trait not in _BIG_FIVE_TRAITS:
                continue
            scaled = base_delta * intensity
            old_val = result.get(trait, baseline.get(trait, 0.5))
            new_val = _clamp(old_val + scaled)
            new_val = _apply_cumulative_cap(
                trait, new_val, baseline.get(trait, 0.5), max_cumulative_drift
            )
            delta[trait] += new_val - old_val
            result[trait] = new_val

    return result, delta


def _apply_monthly_rate_cap(
    current: dict[str, float],
    updated: dict[str, float],
    elapsed_days: float,
    max_drift_per_month: float,
) -> dict[str, float]:
    """
    月あたりの最大変化量（max_drift_per_month）を超えないようにスケールする。

    elapsed_days に比例した上限を計算し、各特性の変化量をクランプする。
    """
    if elapsed_days <= 0.0:
        return dict(updated)

    # elapsed_days 分の最大変化許容量
    max_allowed = max_drift_per_month * (elapsed_days / _DAYS_PER_MONTH)

    result = dict(updated)
    for trait in _BIG_FIVE_TRAITS:
        current_val = current.get(trait, 0.5)
        updated_val = result.get(trait, current_val)
        raw_delta = updated_val - current_val

        if abs(raw_delta) > max_allowed:
            # 方向を保ちつつ最大変化量に収める
            capped_delta = max_allowed * (1.0 if raw_delta > 0 else -1.0)
            result[trait] = _clamp(current_val + capped_delta)

    return result


class ApplyDriftSkill:
    """
    apply_drift Skill の実装。

    体験イベントをもとに Big Five パーソナリティ値を微小変化させる。
    LLM 不要の純粋計算。
    """

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Big Five パーソナリティドリフトを適用する。

        Args:
            params:
                character (str): キャラクター名（必須）
                current_big_five (dict): 現在の Big Five 値（必須）
                baseline_big_five (dict): ベースライン Big Five 値（必須）
                events (list): 体験イベントリスト（省略時: []）
                    各要素: {type: str, intensity: float (0.0〜1.0)}
                elapsed_days (float): 最後のドリフト計算からの経過日数（省略時: 1.0）
                max_drift_per_month (float): 月あたり最大変化量（省略時: 0.05）
                max_cumulative_drift (float): 累積最大ズレ（省略時: 0.20）

        Returns:
            {
                "character": str,
                "updated_big_five": dict[str, float],  # 更新後の Big Five 値
                "drift_applied": dict[str, float],      # 各特性の変化量
                "updated_at": str,                      # ISO 8601 タイムスタンプ
            }
        """
        character: str = params["character"]
        current_big_five: dict[str, float] = {
            t: float(v)
            for t, v in (params.get("current_big_five") or {}).items()
            if t in _BIG_FIVE_TRAITS
        }
        baseline_big_five: dict[str, float] = {
            t: float(v)
            for t, v in (params.get("baseline_big_five") or {}).items()
            if t in _BIG_FIVE_TRAITS
        }
        events: list[dict[str, Any]] = list(params.get("events") or [])
        elapsed_days: float = float(params.get("elapsed_days") or 1.0)
        max_drift_per_month: float = float(params.get("max_drift_per_month") or 0.05)
        max_cumulative_drift: float = float(params.get("max_cumulative_drift") or 0.20)

        # ベースラインが未指定の特性は現在値をベースラインとして使用
        for trait in _BIG_FIVE_TRAITS:
            if trait not in baseline_big_five:
                baseline_big_five[trait] = current_big_five.get(trait, 0.5)

        # 1. イベントに基づくドリフト計算
        updated, delta = _calculate_per_event_drift(
            current_big_five, baseline_big_five, events, max_cumulative_drift
        )

        # 2. 月あたりレート上限の適用
        updated = _apply_monthly_rate_cap(
            current_big_five, updated, elapsed_days, max_drift_per_month
        )

        # 3. 最終的なドリフト量の計算
        final_delta = {
            trait: round(updated.get(trait, current_big_five.get(trait, 0.5))
                         - current_big_five.get(trait, 0.5), 6)
            for trait in _BIG_FIVE_TRAITS
        }

        # 値を 6 桁で丸める
        final_values = {
            trait: round(updated.get(trait, current_big_five.get(trait, 0.5)), 6)
            for trait in _BIG_FIVE_TRAITS
        }

        updated_at = datetime.now(timezone.utc).isoformat()

        logger.debug(
            "apply_drift: character=%s events=%d elapsed_days=%.1f drift=%s",
            character,
            len(events),
            elapsed_days,
            {t: v for t, v in final_delta.items() if abs(v) > 0.0001},
        )

        return {
            "character": character,
            "updated_big_five": final_values,
            "drift_applied": final_delta,
            "updated_at": updated_at,
        }
