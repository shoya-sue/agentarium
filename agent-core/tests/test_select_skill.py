"""
tests/test_select_skill.py — SelectSkillSkill ユニットテスト

LLMClient をモックして Skill 選択ロジックを検証する。
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _make_mock_llm_response(content: str, model: str = "qwen3.5:35b-a3b") -> MagicMock:
    """LLMResponse のモックを作成する。"""
    response = MagicMock()
    response.content = content
    response.model = model
    response.prompt_eval_count = 100
    response.eval_count = 50
    response.eval_duration_ns = 1_000_000_000
    response.tokens_per_second = 50.0
    return response


def _make_llm_client_mock(response_content: str, model: str = "qwen3.5:35b-a3b") -> MagicMock:
    """LLMClient のモックを作成する。"""
    from models.llm import LLMClient
    mock_llm = MagicMock(spec=LLMClient)
    mock_response = _make_mock_llm_response(response_content, model)
    mock_llm.generate = AsyncMock(return_value=mock_response)
    return mock_llm


def _sample_available_skills() -> list[dict]:
    """テスト用 available_skills リストを返す。"""
    return [
        {
            "name": "browse_source",
            "description": "Web ページを取得してコンテンツを収集する",
            "when_to_use": "情報収集が必要な時",
        },
        {
            "name": "store_semantic",
            "description": "収集した情報を Qdrant に保存する",
            "when_to_use": "情報を記憶に保存する時",
        },
        {
            "name": "recall_related",
            "description": "目標に関連する記憶を想起する",
            "when_to_use": "過去の記憶を参照する時",
        },
    ]


def _sample_current_state() -> dict:
    """テスト用 current_state（WorkingMemory.to_summary_dict()相当）を返す。"""
    return {
        "current_goal": "AI 最新情報を収集する",
        "active_character": "zephyr",
        "cycle_count": 3,
        "current_step_index": 0,
        "has_pending_plan": False,
        "plan_steps": [],
        "recent_traces": [],
        "recalled_memories_count": 0,
        "last_updated_at": "2026-04-01T00:00:00+00:00",
    }


class TestSelectSkillSkill:
    """SelectSkillSkill の動作検証"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.reasoning.select_skill import SelectSkillSkill
        assert SelectSkillSkill is not None

    @pytest.mark.asyncio
    async def test_basic_output_structure(self):
        """基本的な出力構造を検証する"""
        from skills.reasoning.select_skill import SelectSkillSkill

        llm_response_json = json.dumps({
            "selected_skill": "browse_source",
            "params": {"url": "https://example.com"},
            "reasoning": "情報収集が最優先タスク",
            "confidence": 0.9,
        })
        mock_llm = _make_llm_client_mock(llm_response_json)
        skill = SelectSkillSkill(llm_client=mock_llm)

        result = await skill.run({
            "available_skills": _sample_available_skills(),
            "current_state": _sample_current_state(),
        })

        assert "selected_skill" in result
        assert "params" in result
        assert "reasoning" in result
        assert "confidence" in result

    @pytest.mark.asyncio
    async def test_valid_skill_selected(self):
        """正常系: available_skills に存在する Skill が選ばれる"""
        from skills.reasoning.select_skill import SelectSkillSkill

        llm_response_json = json.dumps({
            "selected_skill": "browse_source",
            "params": {"url": "https://news.ycombinator.com"},
            "reasoning": "HN を巡回する時間",
            "confidence": 0.85,
        })
        mock_llm = _make_llm_client_mock(llm_response_json)
        skill = SelectSkillSkill(llm_client=mock_llm)

        result = await skill.run({
            "available_skills": _sample_available_skills(),
            "current_state": _sample_current_state(),
        })

        assert result["selected_skill"] == "browse_source"
        assert isinstance(result["params"], dict)
        assert isinstance(result["reasoning"], str)
        assert 0.0 <= result["confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_idle_when_skill_not_in_list(self):
        """存在しない Skill が選択された場合は IDLE にフォールバック"""
        from skills.reasoning.select_skill import SelectSkillSkill

        llm_response_json = json.dumps({
            "selected_skill": "nonexistent_skill",
            "params": {},
            "reasoning": "存在しない Skill",
            "confidence": 0.5,
        })
        mock_llm = _make_llm_client_mock(llm_response_json)
        skill = SelectSkillSkill(llm_client=mock_llm)

        result = await skill.run({
            "available_skills": _sample_available_skills(),
            "current_state": _sample_current_state(),
        })

        assert result["selected_skill"] == "IDLE"

    @pytest.mark.asyncio
    async def test_idle_on_parse_failure(self):
        """LLM の JSON パース失敗時は IDLE にフォールバック"""
        from skills.reasoning.select_skill import SelectSkillSkill

        mock_llm = _make_llm_client_mock("これは JSON ではありません")
        skill = SelectSkillSkill(llm_client=mock_llm)

        result = await skill.run({
            "available_skills": _sample_available_skills(),
            "current_state": _sample_current_state(),
        })

        assert result["selected_skill"] == "IDLE"
        assert result["params"] == {}
        assert "パース失敗" in result["reasoning"]
        assert result["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_idle_skill_is_always_valid(self):
        """LLM が IDLE を選択した場合はそのまま返す"""
        from skills.reasoning.select_skill import SelectSkillSkill

        llm_response_json = json.dumps({
            "selected_skill": "IDLE",
            "params": {},
            "reasoning": "特にすべきことがない",
            "confidence": 1.0,
        })
        mock_llm = _make_llm_client_mock(llm_response_json)
        skill = SelectSkillSkill(llm_client=mock_llm)

        result = await skill.run({
            "available_skills": _sample_available_skills(),
            "current_state": _sample_current_state(),
        })

        assert result["selected_skill"] == "IDLE"
        assert result["confidence"] == 1.0

    @pytest.mark.asyncio
    async def test_timeout_falls_back_to_idle(self):
        """LLM タイムアウト（例外）時は IDLE にフォールバック"""
        from skills.reasoning.select_skill import SelectSkillSkill
        from models.llm import LLMClient

        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.generate = AsyncMock(side_effect=asyncio.TimeoutError("タイムアウト"))
        skill = SelectSkillSkill(llm_client=mock_llm)

        result = await skill.run({
            "available_skills": _sample_available_skills(),
            "current_state": _sample_current_state(),
        })

        assert result["selected_skill"] == "IDLE"
        assert result["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_default_model_is_35b(self):
        """デフォルトモデルは qwen3.5:35b-a3b"""
        from skills.reasoning.select_skill import SelectSkillSkill
        from models.llm import LLMClient

        captured = {}
        mock_llm = MagicMock(spec=LLMClient)

        async def mock_generate(prompt, model, think, extra_options=None):
            captured["model"] = model
            return _make_mock_llm_response(json.dumps({
                "selected_skill": "IDLE",
                "params": {},
                "reasoning": "テスト",
                "confidence": 1.0,
            }))

        mock_llm.generate = mock_generate
        skill = SelectSkillSkill(llm_client=mock_llm)

        await skill.run({
            "available_skills": _sample_available_skills(),
            "current_state": _sample_current_state(),
        })

        assert captured["model"] == "qwen3.5:35b-a3b"

    @pytest.mark.asyncio
    async def test_model_override_via_params(self):
        """params に model が指定された場合はそちらを優先"""
        from skills.reasoning.select_skill import SelectSkillSkill
        from models.llm import LLMClient

        captured = {}
        mock_llm = MagicMock(spec=LLMClient)

        async def mock_generate(prompt, model, think, extra_options=None):
            captured["model"] = model
            return _make_mock_llm_response(json.dumps({
                "selected_skill": "IDLE",
                "params": {},
                "reasoning": "テスト",
                "confidence": 1.0,
            }))

        mock_llm.generate = mock_generate
        skill = SelectSkillSkill(llm_client=mock_llm)

        await skill.run({
            "available_skills": _sample_available_skills(),
            "current_state": _sample_current_state(),
            "model": "qwen3.5:14b",
        })

        assert captured["model"] == "qwen3.5:14b"

    @pytest.mark.asyncio
    async def test_code_block_json_parsed(self):
        """LLM が ```json ブロックで返した場合もパースされる"""
        from skills.reasoning.select_skill import SelectSkillSkill

        llm_response = """選択結果:
```json
{
  "selected_skill": "recall_related",
  "params": {"query": "AI 最新情報"},
  "reasoning": "記憶を想起してから判断する",
  "confidence": 0.7
}
```"""
        mock_llm = _make_llm_client_mock(llm_response)
        skill = SelectSkillSkill(llm_client=mock_llm)

        result = await skill.run({
            "available_skills": _sample_available_skills(),
            "current_state": _sample_current_state(),
        })

        assert result["selected_skill"] == "recall_related"
        assert result["confidence"] == 0.7

    @pytest.mark.asyncio
    async def test_persona_context_accepted(self):
        """persona_context が渡された場合もエラーなく動作する"""
        from skills.reasoning.select_skill import SelectSkillSkill

        llm_response_json = json.dumps({
            "selected_skill": "browse_source",
            "params": {},
            "reasoning": "情報収集",
            "confidence": 0.8,
        })
        mock_llm = _make_llm_client_mock(llm_response_json)
        skill = SelectSkillSkill(llm_client=mock_llm)

        result = await skill.run({
            "available_skills": _sample_available_skills(),
            "current_state": _sample_current_state(),
            "persona_context": {
                "persona_prompt": "あなたは好奇心旺盛な AI です",
                "character_name": "zephyr",
            },
        })

        assert result["selected_skill"] == "browse_source"

    @pytest.mark.asyncio
    async def test_confidence_clamped_to_range(self):
        """confidence は 0.0〜1.0 の範囲に収まる"""
        from skills.reasoning.select_skill import SelectSkillSkill

        # LLM が範囲外の値を返した場合
        llm_response_json = json.dumps({
            "selected_skill": "browse_source",
            "params": {},
            "reasoning": "テスト",
            "confidence": 1.5,  # 範囲外
        })
        mock_llm = _make_llm_client_mock(llm_response_json)
        skill = SelectSkillSkill(llm_client=mock_llm)

        result = await skill.run({
            "available_skills": _sample_available_skills(),
            "current_state": _sample_current_state(),
        })

        assert 0.0 <= result["confidence"] <= 1.0
