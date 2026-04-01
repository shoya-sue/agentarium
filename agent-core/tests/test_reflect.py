"""
tests/test_reflect.py — ReflectSkill ユニットテスト

LLMClient をモックして振り返り・学習ロジックを検証する。
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _make_mock_llm_response(content: str, model: str = "qwen3.5:14b") -> MagicMock:
    """LLMResponse のモックを作成する。"""
    response = MagicMock()
    response.content = content
    response.model = model
    response.prompt_eval_count = 100
    response.eval_count = 50
    response.eval_duration_ns = 1_000_000_000
    response.tokens_per_second = 50.0
    return response


def _make_llm_client_mock(response_content: str, model: str = "qwen3.5:14b") -> MagicMock:
    """LLMClient のモックを作成する。"""
    from models.llm import LLMClient
    mock_llm = MagicMock(spec=LLMClient)
    mock_response = _make_mock_llm_response(response_content, model)
    mock_llm.generate = AsyncMock(return_value=mock_response)
    return mock_llm


def _sample_working_memory_summary() -> dict:
    """テスト用 WorkingMemory.to_summary_dict() の出力を返す。"""
    return {
        "current_goal": "AI 最新情報を収集する",
        "active_character": "zephyr",
        "cycle_count": 5,
        "current_step_index": 4,
        "has_pending_plan": False,
        "plan_steps": [
            {"skill": "browse_source", "order": 0, "done": True, "expected_outcome": "HN記事取得"},
            {"skill": "store_semantic", "order": 1, "done": True, "expected_outcome": "保存完了"},
        ],
        "recent_traces": [
            {"trace_id": "abc", "skill_name": "browse_source", "status": "success"},
            {"trace_id": "def", "skill_name": "store_semantic", "status": "success"},
        ],
        "recalled_memories_count": 3,
        "last_updated_at": "2026-04-01T00:10:00+00:00",
    }


def _sample_reflection_response() -> dict:
    """テスト用 LLM 振り返りレスポンスを返す。"""
    return {
        "cycle_summary": "HN からAI関連記事を5件収集し、意味記憶に保存した。",
        "achievements": ["AI記事を5件収集", "意味記憶への保存成功"],
        "failures": [],
        "key_learnings": ["HN は平日午前に更新頻度が高い"],
        "next_cycle_suggestions": ["GitHub trending も収集対象に追加する"],
        "self_evaluation_score": 0.8,
    }


class TestReflectSkill:
    """ReflectSkill の動作検証"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.reasoning.reflect import ReflectSkill
        assert ReflectSkill is not None

    @pytest.mark.asyncio
    async def test_returns_reflection_dict(self):
        """正常ケース: LLM が JSON を返す → 期待フィールドが全て存在する"""
        from skills.reasoning.reflect import ReflectSkill

        mock_llm = _make_llm_client_mock(json.dumps(_sample_reflection_response()))
        skill = ReflectSkill(llm_client=mock_llm)

        result = await skill.run({
            "working_memory": _sample_working_memory_summary(),
        })

        assert "cycle_summary" in result
        assert "achievements" in result
        assert "failures" in result
        assert "key_learnings" in result
        assert "next_cycle_suggestions" in result
        assert "self_evaluation_score" in result
        assert "model_used" in result

    @pytest.mark.asyncio
    async def test_score_clamped_to_range(self):
        """LLM が 1.5 を返した場合、score は 1.0 にクランプされる"""
        from skills.reasoning.reflect import ReflectSkill

        response = dict(_sample_reflection_response())
        response["self_evaluation_score"] = 1.5  # 範囲外

        mock_llm = _make_llm_client_mock(json.dumps(response))
        skill = ReflectSkill(llm_client=mock_llm)

        result = await skill.run({
            "working_memory": _sample_working_memory_summary(),
        })

        assert result["self_evaluation_score"] == 1.0

    @pytest.mark.asyncio
    async def test_score_clamped_to_zero(self):
        """LLM が -0.5 を返した場合、score は 0.0 にクランプされる"""
        from skills.reasoning.reflect import ReflectSkill

        response = dict(_sample_reflection_response())
        response["self_evaluation_score"] = -0.5  # 範囲外

        mock_llm = _make_llm_client_mock(json.dumps(response))
        skill = ReflectSkill(llm_client=mock_llm)

        result = await skill.run({
            "working_memory": _sample_working_memory_summary(),
        })

        assert result["self_evaluation_score"] == 0.0

    @pytest.mark.asyncio
    async def test_fallback_on_parse_failure(self):
        """LLM が不正 JSON を返す → フォールバック値を返す"""
        from skills.reasoning.reflect import ReflectSkill

        mock_llm = _make_llm_client_mock("これは JSON ではありません")
        skill = ReflectSkill(llm_client=mock_llm)

        result = await skill.run({
            "working_memory": _sample_working_memory_summary(),
        })

        # フォールバック値の確認
        assert result["achievements"] == []
        assert result["failures"] == []
        assert result["key_learnings"] == []
        assert result["next_cycle_suggestions"] == []
        assert result["self_evaluation_score"] == 0.5
        assert "parse_failed" in result["cycle_summary"]

    @pytest.mark.asyncio
    async def test_fallback_on_llm_timeout(self):
        """LLM タイムアウト → フォールバック値を返す"""
        from skills.reasoning.reflect import ReflectSkill
        from models.llm import LLMClient

        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.generate = AsyncMock(side_effect=asyncio.TimeoutError("タイムアウト"))
        skill = ReflectSkill(llm_client=mock_llm)

        result = await skill.run({
            "working_memory": _sample_working_memory_summary(),
        })

        # フォールバック値の確認
        assert result["self_evaluation_score"] == 0.5
        assert result["achievements"] == []
        assert result["key_learnings"] == []

    @pytest.mark.asyncio
    async def test_key_learnings_is_list(self):
        """key_learnings がリスト型である"""
        from skills.reasoning.reflect import ReflectSkill

        mock_llm = _make_llm_client_mock(json.dumps(_sample_reflection_response()))
        skill = ReflectSkill(llm_client=mock_llm)

        result = await skill.run({
            "working_memory": _sample_working_memory_summary(),
        })

        assert isinstance(result["key_learnings"], list)

    @pytest.mark.asyncio
    async def test_next_cycle_suggestions_is_list(self):
        """next_cycle_suggestions がリスト型である"""
        from skills.reasoning.reflect import ReflectSkill

        mock_llm = _make_llm_client_mock(json.dumps(_sample_reflection_response()))
        skill = ReflectSkill(llm_client=mock_llm)

        result = await skill.run({
            "working_memory": _sample_working_memory_summary(),
        })

        assert isinstance(result["next_cycle_suggestions"], list)

    @pytest.mark.asyncio
    async def test_model_used_in_result(self):
        """model_used フィールドが結果に含まれる"""
        from skills.reasoning.reflect import ReflectSkill

        mock_llm = _make_llm_client_mock(json.dumps(_sample_reflection_response()))
        skill = ReflectSkill(llm_client=mock_llm)

        result = await skill.run({
            "working_memory": _sample_working_memory_summary(),
        })

        assert "model_used" in result
        assert isinstance(result["model_used"], str)
        assert len(result["model_used"]) > 0

    @pytest.mark.asyncio
    async def test_default_model_is_14b(self):
        """デフォルトモデルは qwen3.5:14b"""
        from skills.reasoning.reflect import ReflectSkill
        from models.llm import LLMClient

        captured = {}
        mock_llm = MagicMock(spec=LLMClient)

        async def mock_generate(prompt, model, think, extra_options=None):
            captured["model"] = model
            return _make_mock_llm_response(json.dumps(_sample_reflection_response()))

        mock_llm.generate = mock_generate
        skill = ReflectSkill(llm_client=mock_llm)

        await skill.run({
            "working_memory": _sample_working_memory_summary(),
        })

        assert captured["model"] == "qwen3.5:14b"

    @pytest.mark.asyncio
    async def test_model_override_via_params(self):
        """params に model が指定された場合はそちらを優先"""
        from skills.reasoning.reflect import ReflectSkill
        from models.llm import LLMClient

        captured = {}
        mock_llm = MagicMock(spec=LLMClient)

        async def mock_generate(prompt, model, think, extra_options=None):
            captured["model"] = model
            return _make_mock_llm_response(json.dumps(_sample_reflection_response()))

        mock_llm.generate = mock_generate
        skill = ReflectSkill(llm_client=mock_llm)

        await skill.run({
            "working_memory": _sample_working_memory_summary(),
            "model": "qwen3.5:4b",
        })

        assert captured["model"] == "qwen3.5:4b"

    @pytest.mark.asyncio
    async def test_code_block_json_parsed(self):
        """LLM が ```json ブロックで返した場合もパースされる"""
        from skills.reasoning.reflect import ReflectSkill

        llm_response = f"""振り返り結果:
```json
{json.dumps(_sample_reflection_response())}
```"""
        mock_llm = _make_llm_client_mock(llm_response)
        skill = ReflectSkill(llm_client=mock_llm)

        result = await skill.run({
            "working_memory": _sample_working_memory_summary(),
        })

        assert result["self_evaluation_score"] == 0.8
        assert len(result["achievements"]) == 2

    @pytest.mark.asyncio
    async def test_achievements_is_list(self):
        """achievements がリスト型である"""
        from skills.reasoning.reflect import ReflectSkill

        mock_llm = _make_llm_client_mock(json.dumps(_sample_reflection_response()))
        skill = ReflectSkill(llm_client=mock_llm)

        result = await skill.run({
            "working_memory": _sample_working_memory_summary(),
        })

        assert isinstance(result["achievements"], list)

    @pytest.mark.asyncio
    async def test_score_within_valid_range(self):
        """正常なスコアは 0.0〜1.0 の範囲内"""
        from skills.reasoning.reflect import ReflectSkill

        mock_llm = _make_llm_client_mock(json.dumps(_sample_reflection_response()))
        skill = ReflectSkill(llm_client=mock_llm)

        result = await skill.run({
            "working_memory": _sample_working_memory_summary(),
        })

        assert 0.0 <= result["self_evaluation_score"] <= 1.0
