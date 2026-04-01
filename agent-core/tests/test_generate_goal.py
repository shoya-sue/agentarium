"""
tests/test_generate_goal.py — GenerateGoalSkill ユニットテスト

LLMClient をモックして自律目標生成ロジックを検証する。
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
    response.eval_count = 100
    response.eval_duration_ns = 1_500_000_000
    response.tokens_per_second = 66.7
    return response


def _make_llm_client_mock(response_content: str, model: str = "qwen3.5:35b-a3b") -> MagicMock:
    """LLMClient のモックを作成する。"""
    from models.llm import LLMClient
    mock_llm = MagicMock(spec=LLMClient)
    mock_response = _make_mock_llm_response(response_content, model)
    mock_llm.generate = AsyncMock(return_value=mock_response)
    return mock_llm


def _sample_current_state() -> dict:
    """テスト用 current_state を返す。"""
    return {
        "current_goal": "",
        "active_character": "zephyr",
        "cycle_count": 12,
        "has_pending_plan": False,
        "plan_steps": [],
        "recent_traces": [
            {"skill": "fetch_hacker_news", "status": "success", "result_count": 10},
            {"skill": "store_semantic", "status": "success", "result_count": 5},
        ],
        "recalled_memories_count": 3,
        "last_updated_at": "2026-04-01T10:00:00+00:00",
    }


def _valid_goal_response(**overrides) -> str:
    """有効な JSON 目標レスポンスを返す。"""
    data = {
        "goal": "AI 分野の最新トレンドを収集し、Discord に共有する",
        "goal_type": "information_collection",
        "priority": 0.8,
        "reasoning": "サイクル数が増加しており、情報収集タスクを継続すべき状況",
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


class TestGenerateGoalSkillImport:
    """インポートとクラス構造の確認"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.reasoning.generate_goal import GenerateGoalSkill
        assert GenerateGoalSkill is not None

    def test_instantiate(self):
        """LLMClient を渡してインスタンス化できる"""
        from skills.reasoning.generate_goal import GenerateGoalSkill
        mock_llm = MagicMock()
        skill = GenerateGoalSkill(llm_client=mock_llm)
        assert skill is not None

    def test_has_run_method(self):
        """run メソッドが存在する"""
        from skills.reasoning.generate_goal import GenerateGoalSkill
        mock_llm = MagicMock()
        skill = GenerateGoalSkill(llm_client=mock_llm)
        assert callable(skill.run)


class TestGenerateGoalSkillOutput:
    """出力スキーマの検証"""

    def test_basic_output_structure(self):
        """正常な LLM 出力から goal/goal_type/priority/reasoning が返る"""
        from skills.reasoning.generate_goal import GenerateGoalSkill
        mock_llm = _make_llm_client_mock(_valid_goal_response())
        skill = GenerateGoalSkill(llm_client=mock_llm)
        result = asyncio.run(
            skill.run({"current_state": _sample_current_state()})
        )
        assert "goal" in result
        assert "goal_type" in result
        assert "priority" in result
        assert "reasoning" in result

    def test_goal_is_string(self):
        """goal フィールドが文字列である"""
        from skills.reasoning.generate_goal import GenerateGoalSkill
        mock_llm = _make_llm_client_mock(_valid_goal_response())
        skill = GenerateGoalSkill(llm_client=mock_llm)
        result = asyncio.run(
            skill.run({"current_state": _sample_current_state()})
        )
        assert isinstance(result["goal"], str)
        assert len(result["goal"]) > 0

    def test_goal_type_is_valid_value(self):
        """goal_type が定義済みの値である"""
        from skills.reasoning.generate_goal import (
            GenerateGoalSkill,
            VALID_GOAL_TYPES,
        )
        mock_llm = _make_llm_client_mock(_valid_goal_response(goal_type="information_collection"))
        skill = GenerateGoalSkill(llm_client=mock_llm)
        result = asyncio.run(
            skill.run({"current_state": _sample_current_state()})
        )
        assert result["goal_type"] in VALID_GOAL_TYPES

    def test_priority_is_float_in_range(self):
        """priority が 0.0〜1.0 の float である"""
        from skills.reasoning.generate_goal import GenerateGoalSkill
        mock_llm = _make_llm_client_mock(_valid_goal_response(priority=0.75))
        skill = GenerateGoalSkill(llm_client=mock_llm)
        result = asyncio.run(
            skill.run({"current_state": _sample_current_state()})
        )
        assert isinstance(result["priority"], float)
        assert 0.0 <= result["priority"] <= 1.0

    def test_reasoning_is_string(self):
        """reasoning フィールドが文字列である"""
        from skills.reasoning.generate_goal import GenerateGoalSkill
        mock_llm = _make_llm_client_mock(_valid_goal_response())
        skill = GenerateGoalSkill(llm_client=mock_llm)
        result = asyncio.run(
            skill.run({"current_state": _sample_current_state()})
        )
        assert isinstance(result["reasoning"], str)

    def test_goal_content_matches_llm_output(self):
        """goal の内容が LLM 出力と一致する"""
        from skills.reasoning.generate_goal import GenerateGoalSkill
        expected_goal = "Rust の新しいフレームワークを調査する"
        mock_llm = _make_llm_client_mock(_valid_goal_response(goal=expected_goal))
        skill = GenerateGoalSkill(llm_client=mock_llm)
        result = asyncio.run(
            skill.run({"current_state": _sample_current_state()})
        )
        assert result["goal"] == expected_goal


class TestGenerateGoalSkillGoalTypes:
    """goal_type バリエーションの検証"""

    @pytest.mark.parametrize("goal_type", [
        "information_collection",
        "reflection",
        "discord_response",
        "memory_maintenance",
        "idle",
    ])
    def test_valid_goal_types_accepted(self, goal_type):
        """定義済みの goal_type が正常に返る"""
        from skills.reasoning.generate_goal import GenerateGoalSkill
        mock_llm = _make_llm_client_mock(_valid_goal_response(goal_type=goal_type))
        skill = GenerateGoalSkill(llm_client=mock_llm)
        result = asyncio.run(
            skill.run({"current_state": _sample_current_state()})
        )
        assert result["goal_type"] == goal_type

    def test_invalid_goal_type_fallback(self):
        """未知の goal_type は information_collection にフォールバックする"""
        from skills.reasoning.generate_goal import GenerateGoalSkill
        mock_llm = _make_llm_client_mock(_valid_goal_response(goal_type="unknown_type"))
        skill = GenerateGoalSkill(llm_client=mock_llm)
        result = asyncio.run(
            skill.run({"current_state": _sample_current_state()})
        )
        assert result["goal_type"] == "information_collection"


class TestGenerateGoalSkillFallbacks:
    """エラー時フォールバックの検証"""

    def test_json_parse_failure_returns_fallback(self):
        """JSON パース失敗時はフォールバック目標を返す"""
        from skills.reasoning.generate_goal import GenerateGoalSkill, FALLBACK_GOAL
        mock_llm = _make_llm_client_mock("これは JSON ではありません")
        skill = GenerateGoalSkill(llm_client=mock_llm)
        result = asyncio.run(
            skill.run({"current_state": _sample_current_state()})
        )
        assert result["goal"] == FALLBACK_GOAL
        assert result["priority"] == 0.0

    def test_llm_error_returns_fallback(self):
        """LLM 呼び出し失敗時はフォールバック目標を返す"""
        from skills.reasoning.generate_goal import GenerateGoalSkill, FALLBACK_GOAL
        from models.llm import LLMClient
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.generate = AsyncMock(side_effect=ConnectionError("接続失敗"))
        skill = GenerateGoalSkill(llm_client=mock_llm)
        result = asyncio.run(
            skill.run({"current_state": _sample_current_state()})
        )
        assert result["goal"] == FALLBACK_GOAL
        assert result["priority"] == 0.0

    def test_priority_clamp_above_1(self):
        """priority > 1.0 は 1.0 にクランプされる"""
        from skills.reasoning.generate_goal import GenerateGoalSkill
        mock_llm = _make_llm_client_mock(_valid_goal_response(priority=1.5))
        skill = GenerateGoalSkill(llm_client=mock_llm)
        result = asyncio.run(
            skill.run({"current_state": _sample_current_state()})
        )
        assert result["priority"] == 1.0

    def test_priority_clamp_below_0(self):
        """priority < 0.0 は 0.0 にクランプされる"""
        from skills.reasoning.generate_goal import GenerateGoalSkill
        mock_llm = _make_llm_client_mock(_valid_goal_response(priority=-0.5))
        skill = GenerateGoalSkill(llm_client=mock_llm)
        result = asyncio.run(
            skill.run({"current_state": _sample_current_state()})
        )
        assert result["priority"] == 0.0

    def test_code_block_json_parsed(self):
        """```json ... ``` ブロック内の JSON が正しくパースされる"""
        from skills.reasoning.generate_goal import GenerateGoalSkill
        json_in_block = "```json\n" + _valid_goal_response() + "\n```"
        mock_llm = _make_llm_client_mock(json_in_block)
        skill = GenerateGoalSkill(llm_client=mock_llm)
        result = asyncio.run(
            skill.run({"current_state": _sample_current_state()})
        )
        assert result["goal_type"] == "information_collection"


class TestGenerateGoalSkillContext:
    """コンテキストの活用検証"""

    def test_persona_context_used_in_prompt(self):
        """persona_context を渡すと LLM 呼び出し時に使用される"""
        from skills.reasoning.generate_goal import GenerateGoalSkill
        mock_llm = _make_llm_client_mock(_valid_goal_response())
        skill = GenerateGoalSkill(llm_client=mock_llm)
        persona = {"persona_prompt": "Zephyr は探索と発見が好きなキャラクター"}
        asyncio.run(
            skill.run({
                "current_state": _sample_current_state(),
                "persona_context": persona,
            })
        )
        # LLM が呼び出されたことを確認
        mock_llm.generate.assert_called_once()
        call_args = mock_llm.generate.call_args
        prompt = call_args[1].get("prompt") or call_args[0][0]
        assert "Zephyr" in prompt

    def test_recent_memories_included_in_prompt(self):
        """recent_memories を渡すと LLM プロンプトに含まれる"""
        from skills.reasoning.generate_goal import GenerateGoalSkill
        mock_llm = _make_llm_client_mock(_valid_goal_response())
        skill = GenerateGoalSkill(llm_client=mock_llm)
        asyncio.run(
            skill.run({
                "current_state": _sample_current_state(),
                "recent_memories": [
                    {"summary": "Rust の新バージョンがリリースされた", "score": 0.9},
                ],
            })
        )
        call_args = mock_llm.generate.call_args
        prompt = call_args[1].get("prompt") or call_args[0][0]
        assert "Rust" in prompt

    def test_model_override(self):
        """model パラメータを渡すと LLM 呼び出しに反映される"""
        from skills.reasoning.generate_goal import GenerateGoalSkill
        mock_llm = _make_llm_client_mock(_valid_goal_response())
        skill = GenerateGoalSkill(llm_client=mock_llm)
        asyncio.run(
            skill.run({
                "current_state": _sample_current_state(),
                "model": "qwen3.5:14b",
            })
        )
        call_args = mock_llm.generate.call_args
        model_arg = call_args[1].get("model") or call_args[0][1]
        assert model_arg == "qwen3.5:14b"
