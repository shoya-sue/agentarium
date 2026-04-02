"""
tests/skills/character/test_apply_drift.py — ApplyDriftSkill のテスト

TDD: RED → GREEN → REFACTOR
"""

import pytest

from skills.character.apply_drift import (
    ApplyDriftSkill,
    _apply_cumulative_cap,
    _apply_monthly_rate_cap,
    _calculate_per_event_drift,
    _clamp,
)

# ─── ベースライン値（Zephyr）──────────────────────────────

ZEPHYR_BASELINE = {
    "openness": 0.85,
    "conscientiousness": 0.70,
    "extraversion": 0.55,
    "agreeableness": 0.75,
    "neuroticism": 0.25,
}


# ─── ユニットテスト: _clamp ───────────────────────────────

def test_clamp_within_range():
    assert _clamp(0.5) == 0.5

def test_clamp_below_min():
    assert _clamp(-0.1) == 0.0

def test_clamp_above_max():
    assert _clamp(1.1) == 1.0

def test_clamp_at_boundaries():
    assert _clamp(0.0) == 0.0
    assert _clamp(1.0) == 1.0


# ─── ユニットテスト: _apply_cumulative_cap ───────────────

def test_cumulative_cap_within_range():
    """ベースラインから 0.10 の変化は上限 0.20 以内なので許可"""
    result = _apply_cumulative_cap("openness", 0.90, 0.85, 0.20)
    assert result == pytest.approx(0.90, abs=1e-6)

def test_cumulative_cap_upper_limit():
    """ベースライン 0.85 + cap 0.20 = 1.00 を超える値はクランプ"""
    result = _apply_cumulative_cap("openness", 1.05, 0.85, 0.20)
    assert result == pytest.approx(1.00, abs=1e-6)

def test_cumulative_cap_lower_limit():
    """ベースライン 0.85 - cap 0.20 = 0.65 を下回る値はクランプ"""
    result = _apply_cumulative_cap("openness", 0.50, 0.85, 0.20)
    assert result == pytest.approx(0.65, abs=1e-6)


# ─── ユニットテスト: _calculate_per_event_drift ──────────

def test_novel_discoveries_increases_openness():
    """novel_discoveries イベントは openness を増加させる"""
    current = dict(ZEPHYR_BASELINE)
    updated, delta = _calculate_per_event_drift(
        current, ZEPHYR_BASELINE,
        [{"type": "novel_discoveries", "intensity": 1.0}],
        max_cumulative_drift=0.20,
    )
    assert updated["openness"] > current["openness"]
    assert delta["openness"] > 0.0

def test_negative_experiences_increases_neuroticism():
    """negative_experiences は neuroticism を増加させる"""
    current = dict(ZEPHYR_BASELINE)
    updated, delta = _calculate_per_event_drift(
        current, ZEPHYR_BASELINE,
        [{"type": "negative_experiences", "intensity": 1.0}],
        max_cumulative_drift=0.20,
    )
    assert updated["neuroticism"] > current["neuroticism"]
    assert delta["neuroticism"] > 0.0

def test_intensity_scales_drift():
    """intensity=0.5 は intensity=1.0 の半分のドリフト量になる"""
    current = dict(ZEPHYR_BASELINE)
    _, delta_full = _calculate_per_event_drift(
        current, ZEPHYR_BASELINE,
        [{"type": "novel_discoveries", "intensity": 1.0}],
        max_cumulative_drift=0.20,
    )
    _, delta_half = _calculate_per_event_drift(
        current, ZEPHYR_BASELINE,
        [{"type": "novel_discoveries", "intensity": 0.5}],
        max_cumulative_drift=0.20,
    )
    assert abs(delta_half["openness"]) == pytest.approx(
        abs(delta_full["openness"]) * 0.5, abs=1e-6
    )

def test_unknown_event_type_is_ignored():
    """未知のイベントタイプは無視され、値は変化しない"""
    current = dict(ZEPHYR_BASELINE)
    updated, delta = _calculate_per_event_drift(
        current, ZEPHYR_BASELINE,
        [{"type": "unknown_event_xyz", "intensity": 1.0}],
        max_cumulative_drift=0.20,
    )
    assert updated == current
    assert all(abs(v) < 1e-9 for v in delta.values())

def test_cumulative_cap_prevents_overflow():
    """累積ドリフト上限を超えないことを確認"""
    # 高い openness を持つキャラクターに上限 0.10 を設定
    current = {"openness": 0.94, "conscientiousness": 0.70,
               "extraversion": 0.55, "agreeableness": 0.75, "neuroticism": 0.25}
    baseline = dict(ZEPHYR_BASELINE)  # baseline.openness = 0.85

    # 0.94 は baseline(0.85) + cap(0.10) = 0.95 を超えていない → ドリフトは許可
    updated, _ = _calculate_per_event_drift(
        current, baseline,
        [{"type": "novel_discoveries", "intensity": 1.0}] * 5,
        max_cumulative_drift=0.10,
    )
    # baseline 0.85 + cap 0.10 = 0.95 が上限
    assert updated["openness"] <= 0.95 + 1e-9


# ─── ユニットテスト: _apply_monthly_rate_cap ─────────────

def test_monthly_rate_cap_limits_large_change():
    """1日で月間上限 (0.05) を超える変化はキャップされる"""
    current = {"openness": 0.85, "conscientiousness": 0.70,
               "extraversion": 0.55, "agreeableness": 0.75, "neuroticism": 0.25}
    # 1日分の上限 = 0.05 * (1/30) ≈ 0.00167
    updated = {"openness": 0.90, "conscientiousness": 0.70,  # +0.05 は超過
               "extraversion": 0.55, "agreeableness": 0.75, "neuroticism": 0.25}
    result = _apply_monthly_rate_cap(current, updated, elapsed_days=1.0, max_drift_per_month=0.05)
    # 1日分の最大変化量
    max_allowed_1day = 0.05 * (1.0 / 30.0)
    assert result["openness"] <= current["openness"] + max_allowed_1day + 1e-9

def test_monthly_rate_cap_no_change_when_within_limit():
    """変化量が上限以内なら変化しない"""
    current = {"openness": 0.85, "conscientiousness": 0.70,
               "extraversion": 0.55, "agreeableness": 0.75, "neuroticism": 0.25}
    updated = {"openness": 0.851, "conscientiousness": 0.70,  # 微小変化
               "extraversion": 0.55, "agreeableness": 0.75, "neuroticism": 0.25}
    result = _apply_monthly_rate_cap(current, updated, elapsed_days=30.0, max_drift_per_month=0.05)
    assert result["openness"] == pytest.approx(0.851, abs=1e-6)


# ─── 統合テスト: ApplyDriftSkill.run ─────────────────────

@pytest.mark.asyncio
async def test_apply_drift_zephyr_novel_discoveries():
    """Zephyr の novel_discoveries ドリフトが正しく適用される"""
    skill = ApplyDriftSkill()
    result = await skill.run({
        "character": "zephyr",
        "current_big_five": dict(ZEPHYR_BASELINE),
        "baseline_big_five": dict(ZEPHYR_BASELINE),
        "events": [{"type": "novel_discoveries", "intensity": 1.0}],
        "elapsed_days": 30.0,
        "max_drift_per_month": 0.05,
        "max_cumulative_drift": 0.20,
    })

    assert result["character"] == "zephyr"
    assert "updated_big_five" in result
    assert "drift_applied" in result
    assert "updated_at" in result

    # openness が増加している
    assert result["updated_big_five"]["openness"] > ZEPHYR_BASELINE["openness"]
    # 変化量が 5 特性すべて含まれている
    assert set(result["drift_applied"].keys()) == {
        "openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"
    }


@pytest.mark.asyncio
async def test_apply_drift_no_events_no_change():
    """イベントがない場合、値は変化しない"""
    skill = ApplyDriftSkill()
    result = await skill.run({
        "character": "zephyr",
        "current_big_five": dict(ZEPHYR_BASELINE),
        "baseline_big_five": dict(ZEPHYR_BASELINE),
        "events": [],
        "elapsed_days": 30.0,
    })

    for trait in ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"]:
        assert result["updated_big_five"][trait] == pytest.approx(
            ZEPHYR_BASELINE[trait], abs=1e-6
        )
        assert abs(result["drift_applied"][trait]) < 1e-9


@pytest.mark.asyncio
async def test_apply_drift_monthly_cap_respected():
    """月あたり上限が適用され、月間 0.05 を超えない"""
    skill = ApplyDriftSkill()
    # 30日間・多数のイベントで上限テスト
    result = await skill.run({
        "character": "zephyr",
        "current_big_five": dict(ZEPHYR_BASELINE),
        "baseline_big_five": dict(ZEPHYR_BASELINE),
        "events": [{"type": "novel_discoveries", "intensity": 1.0}] * 100,
        "elapsed_days": 30.0,
        "max_drift_per_month": 0.05,
        "max_cumulative_drift": 0.20,
    })

    delta_openness = abs(
        result["updated_big_five"]["openness"] - ZEPHYR_BASELINE["openness"]
    )
    assert delta_openness <= 0.05 + 1e-9


@pytest.mark.asyncio
async def test_apply_drift_lynx_events():
    """Lynx の validated_predictions ドリフト"""
    skill = ApplyDriftSkill()
    lynx_baseline = {
        "openness": 0.55,
        "conscientiousness": 0.90,
        "extraversion": 0.35,
        "agreeableness": 0.50,
        "neuroticism": 0.20,
    }
    result = await skill.run({
        "character": "lynx",
        "current_big_five": dict(lynx_baseline),
        "baseline_big_five": dict(lynx_baseline),
        "events": [{"type": "validated_predictions", "intensity": 1.0}],
        "elapsed_days": 30.0,
        "max_drift_per_month": 0.03,
        "max_cumulative_drift": 0.20,
    })

    assert result["character"] == "lynx"
    # conscientiousness が増加している
    assert result["updated_big_five"]["conscientiousness"] > lynx_baseline["conscientiousness"]


@pytest.mark.asyncio
async def test_apply_drift_values_stay_in_range():
    """ドリフト後の全値が 0.0〜1.0 に収まる"""
    skill = ApplyDriftSkill()
    # 極端な値でテスト
    extreme_baseline = {
        "openness": 0.98,
        "conscientiousness": 0.02,
        "extraversion": 0.99,
        "agreeableness": 0.01,
        "neuroticism": 0.99,
    }
    result = await skill.run({
        "character": "test",
        "current_big_five": dict(extreme_baseline),
        "baseline_big_five": dict(extreme_baseline),
        "events": [
            {"type": "novel_discoveries", "intensity": 1.0},
            {"type": "negative_experiences", "intensity": 1.0},
            {"type": "social_interactions", "intensity": 1.0},
            {"type": "repeated_success", "intensity": 1.0},
        ],
        "elapsed_days": 30.0,
        "max_drift_per_month": 0.05,
        "max_cumulative_drift": 0.20,
    })

    for trait, value in result["updated_big_five"].items():
        assert 0.0 <= value <= 1.0, f"{trait}={value} が範囲外"
