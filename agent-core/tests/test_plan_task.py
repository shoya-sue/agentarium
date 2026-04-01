"""
tests/test_plan_task.py — PlanTaskSkill ユニットテスト

LLMClient をモックして実行計画生成ロジックを検証する。
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
    response.prompt_eval_count = 150
    response.eval_count = 200
    response.eval_duration_ns = 2_000_000_000
    response.tokens_per_second = 100.0
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
            "name": "recall_related",
            "description": "目標に関連する記憶を想起する",
            "when_to_use": "過去の記憶を参照する時",
        },
        {
            "name": "browse_source",
            "description": "Web ページを取得してコンテンツを収集する",
            "when_to_use": "情報収集が必要な時",
        },
        {
            "name": "evaluate_importance",
            "description": "収集したコンテンツの重要度を評価する",
            "when_to_use": "コンテンツをフィルタリングする時",
        },
        {
            "name": "store_semantic",
            "description": "情報を Qdrant に保存する",
            "when_to_use": "情報を記憶に保存する時",
        },
    ]


def _sample_plan_response() -> dict:
    """テスト用 LLM レスポンス（正常な計画）を返す。"""
    return {
        "steps": [
            {
                "skill": "recall_related",
                "params": {"query": "AI 最新情報"},
                "expected_outcome": "関連する過去の記憶が想起される",
                "order": 0,
            },
            {
                "skill": "browse_source",
                "params": {"source_name": "hacker_news"},
                "expected_outcome": "HN のトップ記事が収集される",
                "order": 1,
            },
            {
                "skill": "evaluate_importance",
                "params": {"threshold": 0.4},
                "expected_outcome": "重要なコンテンツが選別される",
                "order": 2,
            },
            {
                "skill": "store_semantic",
                "params": {"collection": "episodic"},
                "expected_outcome": "重要な情報が記憶に保存される",
                "order": 3,
            },
        ],
        "estimated_duration_sec": 120,
    }


class TestPlanTaskSkill:
    """PlanTaskSkill の動作検証"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.reasoning.plan_task import PlanTaskSkill
        assert PlanTaskSkill is not None

    @pytest.mark.asyncio
    async def test_basic_output_structure(self):
        """基本的な出力構造を検証する"""
        from skills.reasoning.plan_task import PlanTaskSkill

        mock_llm = _make_llm_client_mock(json.dumps(_sample_plan_response()))
        skill = PlanTaskSkill(llm_client=mock_llm)

        result = await skill.run({
            "goal": "AI の最新情報を収集して記憶に保存する",
            "available_skills": _sample_available_skills(),
        })

        assert "steps" in result
        assert "estimated_duration_sec" in result

    @pytest.mark.asyncio
    async def test_steps_structure(self):
        """steps は skill, params, expected_outcome, order を含む"""
        from skills.reasoning.plan_task import PlanTaskSkill

        mock_llm = _make_llm_client_mock(json.dumps(_sample_plan_response()))
        skill = PlanTaskSkill(llm_client=mock_llm)

        result = await skill.run({
            "goal": "情報収集",
            "available_skills": _sample_available_skills(),
        })

        assert len(result["steps"]) > 0
        step = result["steps"][0]
        assert "skill" in step
        assert "params" in step
        assert "expected_outcome" in step
        assert "order" in step

    @pytest.mark.asyncio
    async def test_only_valid_skills_in_steps(self):
        """available_skills に存在しない Skill は steps から除外される"""
        from skills.reasoning.plan_task import PlanTaskSkill

        plan_with_invalid = {
            "steps": [
                {
                    "skill": "recall_related",
                    "params": {},
                    "expected_outcome": "記憶想起",
                    "order": 0,
                },
                {
                    "skill": "nonexistent_skill",  # 存在しない Skill
                    "params": {},
                    "expected_outcome": "無効",
                    "order": 1,
                },
                {
                    "skill": "store_semantic",
                    "params": {},
                    "expected_outcome": "保存",
                    "order": 2,
                },
            ],
            "estimated_duration_sec": 60,
        }
        mock_llm = _make_llm_client_mock(json.dumps(plan_with_invalid))
        skill = PlanTaskSkill(llm_client=mock_llm)

        result = await skill.run({
            "goal": "テスト",
            "available_skills": _sample_available_skills(),
        })

        skill_names = [s["skill"] for s in result["steps"]]
        assert "nonexistent_skill" not in skill_names
        assert "recall_related" in skill_names
        assert "store_semantic" in skill_names

    @pytest.mark.asyncio
    async def test_fallback_on_parse_failure(self):
        """JSON パース失敗時は steps=[], estimated_duration_sec=0 にフォールバック"""
        from skills.reasoning.plan_task import PlanTaskSkill

        mock_llm = _make_llm_client_mock("これは JSON ではありません")
        skill = PlanTaskSkill(llm_client=mock_llm)

        result = await skill.run({
            "goal": "テスト目標",
            "available_skills": _sample_available_skills(),
        })

        assert result["steps"] == []
        assert result["estimated_duration_sec"] == 0

    @pytest.mark.asyncio
    async def test_max_steps_limit(self):
        """max_steps を超えるステップは除外される（LLM に制約を渡す）"""
        from skills.reasoning.plan_task import PlanTaskSkill
        from models.llm import LLMClient

        captured = {}
        mock_llm = MagicMock(spec=LLMClient)

        async def mock_generate(prompt, model, think, extra_options=None):
            captured["prompt"] = prompt
            return _make_mock_llm_response(json.dumps({
                "steps": [
                    {"skill": "recall_related", "params": {}, "expected_outcome": "記憶", "order": 0},
                    {"skill": "browse_source", "params": {}, "expected_outcome": "収集", "order": 1},
                ],
                "estimated_duration_sec": 60,
            }))

        mock_llm.generate = mock_generate
        skill = PlanTaskSkill(llm_client=mock_llm)

        await skill.run({
            "goal": "テスト",
            "available_skills": _sample_available_skills(),
            "max_steps": 3,
        })

        # max_steps がプロンプトに含まれることを確認
        assert "3" in captured["prompt"]

    @pytest.mark.asyncio
    async def test_default_max_steps_is_5(self):
        """max_steps のデフォルトは 5"""
        from skills.reasoning.plan_task import PlanTaskSkill
        from models.llm import LLMClient

        captured = {}
        mock_llm = MagicMock(spec=LLMClient)

        async def mock_generate(prompt, model, think, extra_options=None):
            captured["prompt"] = prompt
            return _make_mock_llm_response(json.dumps({
                "steps": [],
                "estimated_duration_sec": 0,
            }))

        mock_llm.generate = mock_generate
        skill = PlanTaskSkill(llm_client=mock_llm)

        await skill.run({
            "goal": "テスト",
            "available_skills": _sample_available_skills(),
        })

        # デフォルト max_steps=5 がプロンプトに含まれることを確認
        assert "5" in captured["prompt"]

    @pytest.mark.asyncio
    async def test_timeout_falls_back_to_empty(self):
        """LLM タイムアウト（例外）時は空の計画にフォールバック"""
        from skills.reasoning.plan_task import PlanTaskSkill
        from models.llm import LLMClient

        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.generate = AsyncMock(side_effect=asyncio.TimeoutError("タイムアウト"))
        skill = PlanTaskSkill(llm_client=mock_llm)

        result = await skill.run({
            "goal": "タイムアウトテスト",
            "available_skills": _sample_available_skills(),
        })

        assert result["steps"] == []
        assert result["estimated_duration_sec"] == 0

    @pytest.mark.asyncio
    async def test_default_model_is_35b(self):
        """デフォルトモデルは qwen3.5:35b-a3b"""
        from skills.reasoning.plan_task import PlanTaskSkill
        from models.llm import LLMClient

        captured = {}
        mock_llm = MagicMock(spec=LLMClient)

        async def mock_generate(prompt, model, think, extra_options=None):
            captured["model"] = model
            return _make_mock_llm_response(json.dumps({
                "steps": [],
                "estimated_duration_sec": 0,
            }))

        mock_llm.generate = mock_generate
        skill = PlanTaskSkill(llm_client=mock_llm)

        await skill.run({
            "goal": "テスト",
            "available_skills": _sample_available_skills(),
        })

        assert captured["model"] == "qwen3.5:35b-a3b"

    @pytest.mark.asyncio
    async def test_model_override_via_params(self):
        """params に model が指定された場合はそちらを優先"""
        from skills.reasoning.plan_task import PlanTaskSkill
        from models.llm import LLMClient

        captured = {}
        mock_llm = MagicMock(spec=LLMClient)

        async def mock_generate(prompt, model, think, extra_options=None):
            captured["model"] = model
            return _make_mock_llm_response(json.dumps({
                "steps": [],
                "estimated_duration_sec": 0,
            }))

        mock_llm.generate = mock_generate
        skill = PlanTaskSkill(llm_client=mock_llm)

        await skill.run({
            "goal": "テスト",
            "available_skills": _sample_available_skills(),
            "model": "qwen3.5:14b",
        })

        assert captured["model"] == "qwen3.5:14b"

    @pytest.mark.asyncio
    async def test_goal_included_in_prompt(self):
        """goal がプロンプトに含まれる"""
        from skills.reasoning.plan_task import PlanTaskSkill
        from models.llm import LLMClient

        captured = {}
        mock_llm = MagicMock(spec=LLMClient)

        async def mock_generate(prompt, model, think, extra_options=None):
            captured["prompt"] = prompt
            return _make_mock_llm_response(json.dumps({
                "steps": [],
                "estimated_duration_sec": 0,
            }))

        mock_llm.generate = mock_generate
        skill = PlanTaskSkill(llm_client=mock_llm)

        await skill.run({
            "goal": "ユニークな目標テキスト_12345",
            "available_skills": _sample_available_skills(),
        })

        assert "ユニークな目標テキスト_12345" in captured["prompt"]

    @pytest.mark.asyncio
    async def test_context_included_in_prompt(self):
        """context が渡された場合はプロンプトに含まれる"""
        from skills.reasoning.plan_task import PlanTaskSkill
        from models.llm import LLMClient

        captured = {}
        mock_llm = MagicMock(spec=LLMClient)

        async def mock_generate(prompt, model, think, extra_options=None):
            captured["prompt"] = prompt
            return _make_mock_llm_response(json.dumps({
                "steps": [],
                "estimated_duration_sec": 0,
            }))

        mock_llm.generate = mock_generate
        skill = PlanTaskSkill(llm_client=mock_llm)

        await skill.run({
            "goal": "テスト",
            "available_skills": _sample_available_skills(),
            "context": {"last_result": "前回の実行でエラーが発生した"},
        })

        assert "前回の実行でエラーが発生した" in captured["prompt"]

    @pytest.mark.asyncio
    async def test_code_block_json_parsed(self):
        """LLM が ```json ブロックで返した場合もパースされる"""
        from skills.reasoning.plan_task import PlanTaskSkill

        llm_response = """計画を立案しました:
```json
{
  "steps": [
    {"skill": "recall_related", "params": {}, "expected_outcome": "記憶想起", "order": 0}
  ],
  "estimated_duration_sec": 30
}
```"""
        mock_llm = _make_llm_client_mock(llm_response)
        skill = PlanTaskSkill(llm_client=mock_llm)

        result = await skill.run({
            "goal": "テスト",
            "available_skills": _sample_available_skills(),
        })

        assert len(result["steps"]) == 1
        assert result["steps"][0]["skill"] == "recall_related"
        assert result["estimated_duration_sec"] == 30

    @pytest.mark.asyncio
    async def test_estimated_duration_is_int(self):
        """estimated_duration_sec は整数型"""
        from skills.reasoning.plan_task import PlanTaskSkill

        mock_llm = _make_llm_client_mock(json.dumps(_sample_plan_response()))
        skill = PlanTaskSkill(llm_client=mock_llm)

        result = await skill.run({
            "goal": "テスト",
            "available_skills": _sample_available_skills(),
        })

        assert isinstance(result["estimated_duration_sec"], int)
