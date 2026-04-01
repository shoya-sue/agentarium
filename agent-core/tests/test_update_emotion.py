"""
tests/test_update_emotion.py — UpdateEmotionSkill ユニットテスト

感情状態の更新・delta 適用・減衰ロジックを検証する。
LLM/Qdrant 不要（純粋計算）。
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# テスト用のデフォルト感情状態（Zephyr の active_axes）
_DEFAULT_STATE = {
    "curiosity": 0.5,
    "excitement": 0.5,
    "anticipation": 0.5,
    "boredom": 0.3,
    "awe": 0.5,
    "joy": 0.5,
    "satisfaction": 0.5,
    "restlessness": 0.5,
    "anxiety": 0.2,
    "pride": 0.5,
}


class TestUpdateEmotionSkillImport:
    """インポートとクラス構造の確認"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.character.update_emotion import UpdateEmotionSkill
        assert UpdateEmotionSkill is not None

    def test_instantiate(self):
        """インスタンス化できる"""
        from skills.character.update_emotion import UpdateEmotionSkill
        skill = UpdateEmotionSkill()
        assert skill is not None

    def test_has_run_method(self):
        """run メソッドが存在する"""
        from skills.character.update_emotion import UpdateEmotionSkill
        skill = UpdateEmotionSkill()
        assert callable(skill.run)

    def test_neutral_point_constant(self):
        """NEUTRAL_POINT 定数が 0.5 である"""
        from skills.character.update_emotion import NEUTRAL_POINT
        assert NEUTRAL_POINT == 0.5

    def test_decay_rate_constant(self):
        """DECAY_RATE_PER_HOUR 定数が存在する"""
        from skills.character.update_emotion import DECAY_RATE_PER_HOUR
        assert 0.0 < DECAY_RATE_PER_HOUR <= 1.0


class TestUpdateEmotionSkillOutput:
    """出力スキーマの検証"""

    def test_basic_output_structure(self):
        """出力に state / updated_at / character が含まれる"""
        from skills.character.update_emotion import UpdateEmotionSkill
        skill = UpdateEmotionSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": _DEFAULT_STATE.copy(),
                "delta": {},
            })
        )
        assert "state" in result
        assert "character" in result
        assert "updated_at" in result

    def test_state_is_dict(self):
        """state がディクショナリである"""
        from skills.character.update_emotion import UpdateEmotionSkill
        skill = UpdateEmotionSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": _DEFAULT_STATE.copy(),
                "delta": {},
            })
        )
        assert isinstance(result["state"], dict)

    def test_character_in_output(self):
        """character フィールドが入力と一致する"""
        from skills.character.update_emotion import UpdateEmotionSkill
        skill = UpdateEmotionSkill()
        result = asyncio.run(
            skill.run({
                "character": "lynx",
                "current_state": {"curiosity": 0.5},
                "delta": {},
            })
        )
        assert result["character"] == "lynx"

    def test_updated_at_is_iso_string(self):
        """updated_at が ISO 形式の文字列である"""
        from skills.character.update_emotion import UpdateEmotionSkill
        skill = UpdateEmotionSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": _DEFAULT_STATE.copy(),
                "delta": {},
            })
        )
        assert isinstance(result["updated_at"], str)
        assert "T" in result["updated_at"]


class TestUpdateEmotionSkillDelta:
    """delta 適用の検証"""

    def test_positive_delta_increases_value(self):
        """正の delta で感情値が増加する"""
        from skills.character.update_emotion import UpdateEmotionSkill
        skill = UpdateEmotionSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {"curiosity": 0.5},
                "delta": {"curiosity": 0.2},
            })
        )
        assert result["state"]["curiosity"] > 0.5

    def test_negative_delta_decreases_value(self):
        """負の delta で感情値が減少する"""
        from skills.character.update_emotion import UpdateEmotionSkill
        skill = UpdateEmotionSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {"frustration": 0.6},
                "delta": {"frustration": -0.15},
            })
        )
        assert result["state"]["frustration"] < 0.6

    def test_delta_clamped_to_max_1(self):
        """delta 適用後の値が 1.0 を超えない"""
        from skills.character.update_emotion import UpdateEmotionSkill
        skill = UpdateEmotionSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {"joy": 0.9},
                "delta": {"joy": 0.5},  # 0.9 + 0.5 = 1.4 → 1.0 にクランプ
            })
        )
        assert result["state"]["joy"] == 1.0

    def test_delta_clamped_to_min_0(self):
        """delta 適用後の値が 0.0 を下回らない"""
        from skills.character.update_emotion import UpdateEmotionSkill
        skill = UpdateEmotionSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {"anxiety": 0.1},
                "delta": {"anxiety": -0.5},  # 0.1 - 0.5 = -0.4 → 0.0 にクランプ
            })
        )
        assert result["state"]["anxiety"] == 0.0

    def test_unknown_axis_in_delta_ignored(self):
        """current_state に存在しない軸の delta は無視される"""
        from skills.character.update_emotion import UpdateEmotionSkill
        skill = UpdateEmotionSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {"curiosity": 0.5},
                "delta": {"nonexistent_axis": 0.9},
            })
        )
        assert "nonexistent_axis" not in result["state"]
        assert result["state"]["curiosity"] == pytest.approx(0.5, abs=0.15)

    def test_empty_delta_state_unchanged(self):
        """delta が空の場合、現在の状態が維持される（減衰なし）"""
        from skills.character.update_emotion import UpdateEmotionSkill
        skill = UpdateEmotionSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {"curiosity": 0.7},
                "delta": {},
                "elapsed_hours": 0.0,  # 経過時間 0 → 減衰なし
            })
        )
        assert result["state"]["curiosity"] == pytest.approx(0.7)

    def test_skill_success_trigger(self):
        """trigger=skill_success で satisfaction/pride が上昇する"""
        from skills.character.update_emotion import UpdateEmotionSkill
        skill = UpdateEmotionSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {
                    "satisfaction": 0.5,
                    "frustration": 0.5,
                    "pride": 0.5,
                },
                "trigger": "skill_success",
            })
        )
        assert result["state"]["satisfaction"] > 0.5
        assert result["state"]["pride"] > 0.5

    def test_skill_failure_trigger(self):
        """trigger=skill_failure で frustration/anxiety が上昇する"""
        from skills.character.update_emotion import UpdateEmotionSkill
        skill = UpdateEmotionSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {
                    "frustration": 0.3,
                    "satisfaction": 0.7,
                    "anxiety": 0.2,
                },
                "trigger": "skill_failure",
            })
        )
        assert result["state"]["frustration"] > 0.3
        assert result["state"]["anxiety"] > 0.2


class TestUpdateEmotionSkillDecay:
    """時間経過による減衰の検証"""

    def test_decay_moves_toward_neutral(self):
        """elapsed_hours > 0 で中立点（0.5）に近づく"""
        from skills.character.update_emotion import UpdateEmotionSkill
        skill = UpdateEmotionSkill()
        # 高い値は下がる
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {"curiosity": 0.9},
                "delta": {},
                "elapsed_hours": 1.0,
            })
        )
        assert result["state"]["curiosity"] < 0.9
        assert result["state"]["curiosity"] >= 0.5  # 中立点を下回らない（この1hで）

    def test_decay_from_below_neutral_moves_up(self):
        """中立点以下の値は減衰で上昇する"""
        from skills.character.update_emotion import UpdateEmotionSkill
        skill = UpdateEmotionSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {"anxiety": 0.1},
                "delta": {},
                "elapsed_hours": 1.0,
            })
        )
        assert result["state"]["anxiety"] > 0.1

    def test_neutral_point_stays_unchanged_with_decay(self):
        """中立点の値は減衰で変化しない"""
        from skills.character.update_emotion import UpdateEmotionSkill
        skill = UpdateEmotionSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {"joy": 0.5},
                "delta": {},
                "elapsed_hours": 2.0,
            })
        )
        assert result["state"]["joy"] == pytest.approx(0.5)

    def test_zero_elapsed_hours_no_decay(self):
        """elapsed_hours=0 で減衰しない"""
        from skills.character.update_emotion import UpdateEmotionSkill
        skill = UpdateEmotionSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {"excitement": 0.8},
                "delta": {},
                "elapsed_hours": 0.0,
            })
        )
        assert result["state"]["excitement"] == pytest.approx(0.8)
