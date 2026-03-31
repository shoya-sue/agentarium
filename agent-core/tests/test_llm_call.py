"""
tests/test_llm_call.py — LlmCallSkill ユニットテスト

LLMClient をモックして Skill の入出力変換を検証する。
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _make_routing_config(tmp_path: Path, model: str = "test-model") -> Path:
    """テスト用 routing.yaml を作成する。"""
    import yaml
    llm_dir = tmp_path / "llm"
    llm_dir.mkdir(parents=True)
    (llm_dir / "routing.yaml").write_text(
        yaml.dump({"default_model": model})
    )
    return tmp_path


def _make_mock_llm_response(content: str = "テスト応答", model: str = "test-model") -> MagicMock:
    """LLMResponse のモックを作成する。"""
    response = MagicMock()
    response.content = content
    response.model = model
    response.prompt_eval_count = 10
    response.eval_count = 5
    response.eval_duration_ns = 1_000_000_000  # 1秒
    response.tokens_per_second = 5.0
    return response


class TestLlmCallSkill:
    """LlmCallSkill の動作検証"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.reasoning.llm_call import LlmCallSkill
        assert LlmCallSkill is not None

    def test_messages_to_prompt_conversion(self):
        """messages 配列が単一プロンプト文字列に変換される"""
        from skills.reasoning.llm_call import _messages_to_prompt
        messages = [
            {"role": "system", "content": "あなたはAIです"},
            {"role": "user", "content": "こんにちは"},
        ]
        prompt = _messages_to_prompt(messages)
        assert "System: あなたはAIです" in prompt
        assert "User: こんにちは" in prompt

    def test_messages_to_prompt_empty(self):
        """空のメッセージ配列は空文字を返す"""
        from skills.reasoning.llm_call import _messages_to_prompt
        assert _messages_to_prompt([]) == ""

    @pytest.mark.asyncio
    async def test_run_calls_llm_and_returns_result(self, tmp_path: Path):
        """LLM を呼び出して結果を正しい形式で返す"""
        from skills.reasoning.llm_call import LlmCallSkill
        from models.llm import LLMClient

        config_dir = _make_routing_config(tmp_path)
        mock_llm = MagicMock(spec=LLMClient)
        mock_response = _make_mock_llm_response("テスト応答", "test-model")
        mock_llm.generate = AsyncMock(return_value=mock_response)

        skill = LlmCallSkill(llm_client=mock_llm, config_dir=config_dir)

        result = await skill.run({
            "messages": [
                {"role": "system", "content": "システムプロンプト"},
                {"role": "user", "content": "質問"},
            ]
        })

        assert result["content"] == "テスト応答"
        assert result["model"] == "test-model"
        assert "tokens_used" in result
        assert result["tokens_used"]["total"] == 15  # 10 + 5

    @pytest.mark.asyncio
    async def test_model_override(self, tmp_path: Path):
        """params["model"] でモデルを上書きできる"""
        from skills.reasoning.llm_call import LlmCallSkill
        from models.llm import LLMClient

        config_dir = _make_routing_config(tmp_path, model="default-model")
        mock_llm = MagicMock(spec=LLMClient)
        mock_response = _make_mock_llm_response("上書き応答", "override-model")

        captured_model = {}

        async def mock_generate(prompt, model, think, extra_options=None):
            captured_model["model"] = model
            return mock_response

        mock_llm.generate = mock_generate

        skill = LlmCallSkill(llm_client=mock_llm, config_dir=config_dir)
        await skill.run({
            "messages": [{"role": "user", "content": "test"}],
            "model": "override-model",
        })

        assert captured_model["model"] == "override-model"

    @pytest.mark.asyncio
    async def test_tokens_used_fields(self, tmp_path: Path):
        """tokens_used に prompt / completion / total フィールドが含まれる"""
        from skills.reasoning.llm_call import LlmCallSkill
        from models.llm import LLMClient

        config_dir = _make_routing_config(tmp_path)
        mock_llm = MagicMock(spec=LLMClient)
        mock_response = _make_mock_llm_response()
        mock_llm.generate = AsyncMock(return_value=mock_response)

        skill = LlmCallSkill(llm_client=mock_llm, config_dir=config_dir)
        result = await skill.run({
            "messages": [{"role": "user", "content": "hi"}]
        })

        tokens = result["tokens_used"]
        assert "prompt" in tokens
        assert "completion" in tokens
        assert "total" in tokens
        assert tokens["total"] == tokens["prompt"] + tokens["completion"]
