"""
tests/test_update_character_state.py — UpdateCharacterStateSkill ユニットテスト

L4 Cognitive State（疲労・認知負荷・集中）の更新ロジックを検証する。
LLM 不要（純粋計算）。
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# テスト用のデフォルト認知状態
_DEFAULT_STATE = {
    "cognitive_load": 0.3,
    "fatigue": 0.0,
    "focus": 0.7,
}


class TestUpdateCharacterStateSkillImport:
    """インポートとクラス構造の確認"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.character.update_character_state import UpdateCharacterStateSkill
        assert UpdateCharacterStateSkill is not None

    def test_instantiate(self):
        """インスタンス化できる"""
        from skills.character.update_character_state import UpdateCharacterStateSkill
        skill = UpdateCharacterStateSkill()
        assert skill is not None

    def test_has_run_method(self):
        """run メソッドが存在する"""
        from skills.character.update_character_state import UpdateCharacterStateSkill
        skill = UpdateCharacterStateSkill()
        assert callable(skill.run)


class TestUpdateCharacterStateSkillOutput:
    """出力スキーマの検証"""

    def test_basic_output_structure(self):
        """出力に state / character / updated_at が含まれる"""
        from skills.character.update_character_state import UpdateCharacterStateSkill
        skill = UpdateCharacterStateSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": _DEFAULT_STATE.copy(),
                "trigger": "skill_execution",
            })
        )
        assert "state" in result
        assert "character" in result
        assert "updated_at" in result

    def test_state_contains_required_fields(self):
        """state に cognitive_load / fatigue / focus が含まれる"""
        from skills.character.update_character_state import UpdateCharacterStateSkill
        skill = UpdateCharacterStateSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": _DEFAULT_STATE.copy(),
                "trigger": "skill_execution",
            })
        )
        state = result["state"]
        assert "cognitive_load" in state
        assert "fatigue" in state
        assert "focus" in state

    def test_all_values_in_range(self):
        """すべての状態値が 0.0〜1.0 の範囲内にある"""
        from skills.character.update_character_state import UpdateCharacterStateSkill
        skill = UpdateCharacterStateSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": _DEFAULT_STATE.copy(),
                "trigger": "skill_execution",
            })
        )
        for key, val in result["state"].items():
            assert 0.0 <= val <= 1.0, f"{key}={val} が範囲外"

    def test_character_in_output(self):
        """character フィールドが入力と一致する"""
        from skills.character.update_character_state import UpdateCharacterStateSkill
        skill = UpdateCharacterStateSkill()
        result = asyncio.run(
            skill.run({
                "character": "lynx",
                "current_state": _DEFAULT_STATE.copy(),
            })
        )
        assert result["character"] == "lynx"


class TestUpdateCharacterStateTriggers:
    """トリガー別の更新検証"""

    def test_skill_execution_increases_cognitive_load(self):
        """skill_execution で cognitive_load が増加する"""
        from skills.character.update_character_state import UpdateCharacterStateSkill
        skill = UpdateCharacterStateSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {"cognitive_load": 0.3, "fatigue": 0.0, "focus": 0.7},
                "trigger": "skill_execution",
            })
        )
        assert result["state"]["cognitive_load"] > 0.3

    def test_skill_execution_increases_fatigue(self):
        """skill_execution で fatigue が増加する"""
        from skills.character.update_character_state import UpdateCharacterStateSkill
        skill = UpdateCharacterStateSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {"cognitive_load": 0.3, "fatigue": 0.0, "focus": 0.7},
                "trigger": "skill_execution",
            })
        )
        assert result["state"]["fatigue"] > 0.0

    def test_llm_heavy_task_increases_cognitive_load_more(self):
        """llm_heavy_task で cognitive_load が skill_execution より多く増加する"""
        from skills.character.update_character_state import UpdateCharacterStateSkill
        skill = UpdateCharacterStateSkill()
        base_state = {"cognitive_load": 0.3, "fatigue": 0.0, "focus": 0.5}

        result_skill = asyncio.run(
            skill.run({"character": "zephyr", "current_state": base_state.copy(), "trigger": "skill_execution"})
        )
        result_llm = asyncio.run(
            skill.run({"character": "zephyr", "current_state": base_state.copy(), "trigger": "llm_heavy_task"})
        )
        assert result_llm["state"]["cognitive_load"] > result_skill["state"]["cognitive_load"]

    def test_idle_period_decreases_cognitive_load(self):
        """idle_period で cognitive_load が減少する"""
        from skills.character.update_character_state import UpdateCharacterStateSkill
        skill = UpdateCharacterStateSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {"cognitive_load": 0.5, "fatigue": 0.3, "focus": 0.7},
                "trigger": "idle_period",
            })
        )
        assert result["state"]["cognitive_load"] < 0.5

    def test_idle_period_decreases_fatigue(self):
        """idle_period で fatigue が減少する"""
        from skills.character.update_character_state import UpdateCharacterStateSkill
        skill = UpdateCharacterStateSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {"cognitive_load": 0.5, "fatigue": 0.3, "focus": 0.7},
                "trigger": "idle_period",
            })
        )
        assert result["state"]["fatigue"] < 0.3

    def test_topic_switch_resets_focus(self):
        """topic_switch で focus が 0.3 にリセットされる"""
        from skills.character.update_character_state import UpdateCharacterStateSkill
        skill = UpdateCharacterStateSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {"cognitive_load": 0.4, "fatigue": 0.2, "focus": 0.9},
                "trigger": "topic_switch",
            })
        )
        assert result["state"]["focus"] == pytest.approx(0.3)

    def test_no_trigger_state_unchanged(self):
        """trigger なし（elapsed_hours=0）では状態が変化しない"""
        from skills.character.update_character_state import UpdateCharacterStateSkill
        skill = UpdateCharacterStateSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {"cognitive_load": 0.4, "fatigue": 0.2, "focus": 0.6},
                "elapsed_hours": 0.0,
            })
        )
        assert result["state"]["cognitive_load"] == pytest.approx(0.4)
        assert result["state"]["fatigue"] == pytest.approx(0.2)
        assert result["state"]["focus"] == pytest.approx(0.6)

    def test_clamping_at_max(self):
        """値が 1.0 を超えないようにクランプされる"""
        from skills.character.update_character_state import UpdateCharacterStateSkill
        skill = UpdateCharacterStateSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {"cognitive_load": 0.99, "fatigue": 0.99, "focus": 0.5},
                "trigger": "skill_execution",
            })
        )
        assert result["state"]["cognitive_load"] <= 1.0
        assert result["state"]["fatigue"] <= 1.0

    def test_clamping_at_min(self):
        """値が 0.0 を下回らないようにクランプされる"""
        from skills.character.update_character_state import UpdateCharacterStateSkill
        skill = UpdateCharacterStateSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {"cognitive_load": 0.01, "fatigue": 0.01, "focus": 0.5},
                "trigger": "idle_period",
            })
        )
        assert result["state"]["cognitive_load"] >= 0.0
        assert result["state"]["fatigue"] >= 0.0


class TestUpdateCharacterStateFatigueAccumulation:
    """時間経過による疲労蓄積の検証"""

    def test_fatigue_accumulates_over_time(self):
        """elapsed_hours > 0 で疲労が蓄積する"""
        from skills.character.update_character_state import UpdateCharacterStateSkill
        skill = UpdateCharacterStateSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {"cognitive_load": 0.3, "fatigue": 0.0, "focus": 0.7},
                "elapsed_hours": 1.0,
            })
        )
        assert result["state"]["fatigue"] > 0.0

    def test_zero_hours_no_accumulation(self):
        """elapsed_hours=0 では疲労蓄積なし"""
        from skills.character.update_character_state import UpdateCharacterStateSkill
        skill = UpdateCharacterStateSkill()
        result = asyncio.run(
            skill.run({
                "character": "zephyr",
                "current_state": {"cognitive_load": 0.3, "fatigue": 0.2, "focus": 0.7},
                "elapsed_hours": 0.0,
            })
        )
        assert result["state"]["fatigue"] == pytest.approx(0.2)
