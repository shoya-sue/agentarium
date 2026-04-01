"""
tests/test_evaluate_importance.py — EvaluateImportanceSkill ユニットテスト

LLMClient をモックして重要度評価ロジックを検証する。
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _make_mock_llm_response(content: str, model: str = "qwen3.5:4b") -> MagicMock:
    """LLMResponse のモックを作成する。"""
    response = MagicMock()
    response.content = content
    response.model = model
    response.prompt_eval_count = 50
    response.eval_count = 30
    response.eval_duration_ns = 500_000_000
    response.tokens_per_second = 60.0
    return response


def _make_llm_client_mock(response_content: str, model: str = "qwen3.5:4b") -> MagicMock:
    """LLMClient のモックを作成する。"""
    from models.llm import LLMClient
    mock_llm = MagicMock(spec=LLMClient)
    mock_response = _make_mock_llm_response(response_content, model)
    mock_llm.generate = AsyncMock(return_value=mock_response)
    return mock_llm


class TestEvaluateImportanceSkill:
    """EvaluateImportanceSkill の動作検証"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.memory.evaluate_importance import EvaluateImportanceSkill
        assert EvaluateImportanceSkill is not None

    @pytest.mark.asyncio
    async def test_basic_output_structure(self):
        """基本的な出力構造を検証する"""
        from skills.memory.evaluate_importance import EvaluateImportanceSkill

        llm_response_json = json.dumps({
            "importance_score": 0.7,
            "reasoning": "技術的なトレンド記事で重要度が高い",
            "topics": ["AI", "LLM", "Python"],
        })
        mock_llm = _make_llm_client_mock(llm_response_json)
        skill = EvaluateImportanceSkill(llm_client=mock_llm)

        result = await skill.run({
            "content": "Qwen3.5 が新しいアーキテクチャを採用した",
            "source": "github_trending",
        })

        assert "importance_score" in result
        assert "reasoning" in result
        assert "topics" in result
        assert "should_store" in result

    @pytest.mark.asyncio
    async def test_importance_score_range(self):
        """importance_score は 0.0〜1.0 の範囲に収まる"""
        from skills.memory.evaluate_importance import EvaluateImportanceSkill

        llm_response_json = json.dumps({
            "importance_score": 0.8,
            "reasoning": "重要な情報",
            "topics": ["AI"],
        })
        mock_llm = _make_llm_client_mock(llm_response_json)
        skill = EvaluateImportanceSkill(llm_client=mock_llm)

        result = await skill.run({
            "content": "テストコンテンツ",
            "source": "test_source",
        })

        assert 0.0 <= result["importance_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_should_store_true_when_score_above_threshold(self):
        """importance_score >= 0.4 の場合 should_store は True"""
        from skills.memory.evaluate_importance import EvaluateImportanceSkill

        llm_response_json = json.dumps({
            "importance_score": 0.6,
            "reasoning": "十分重要",
            "topics": ["Python"],
        })
        mock_llm = _make_llm_client_mock(llm_response_json)
        skill = EvaluateImportanceSkill(llm_client=mock_llm)

        result = await skill.run({
            "content": "重要なコンテンツ",
            "source": "hacker_news",
        })

        assert result["should_store"] is True

    @pytest.mark.asyncio
    async def test_should_store_false_when_score_below_threshold(self):
        """importance_score < 0.4 の場合 should_store は False"""
        from skills.memory.evaluate_importance import EvaluateImportanceSkill

        llm_response_json = json.dumps({
            "importance_score": 0.2,
            "reasoning": "重要度が低い",
            "topics": [],
        })
        mock_llm = _make_llm_client_mock(llm_response_json)
        skill = EvaluateImportanceSkill(llm_client=mock_llm)

        result = await skill.run({
            "content": "あまり重要でないコンテンツ",
            "source": "rss_feed",
        })

        assert result["should_store"] is False

    @pytest.mark.asyncio
    async def test_should_store_true_at_threshold(self):
        """importance_score == 0.4 の場合 should_store は True（境界値）"""
        from skills.memory.evaluate_importance import EvaluateImportanceSkill

        llm_response_json = json.dumps({
            "importance_score": 0.4,
            "reasoning": "ちょうど閾値",
            "topics": ["Tech"],
        })
        mock_llm = _make_llm_client_mock(llm_response_json)
        skill = EvaluateImportanceSkill(llm_client=mock_llm)

        result = await skill.run({
            "content": "境界値テスト",
            "source": "test",
        })

        assert result["should_store"] is True

    @pytest.mark.asyncio
    async def test_fallback_on_parse_failure(self):
        """LLM の出力が不正な JSON の場合はデフォルト値（score=0.5）にフォールバック"""
        from skills.memory.evaluate_importance import EvaluateImportanceSkill

        mock_llm = _make_llm_client_mock("これは JSON ではありません。テキストです。")
        skill = EvaluateImportanceSkill(llm_client=mock_llm)

        result = await skill.run({
            "content": "テストコンテンツ",
            "source": "test_source",
        })

        # フォールバック値 0.5 が使用される
        assert result["importance_score"] == 0.5
        assert isinstance(result["reasoning"], str)
        assert isinstance(result["topics"], list)

    @pytest.mark.asyncio
    async def test_default_model_is_4b(self):
        """デフォルトモデルは qwen3.5:4b"""
        from skills.memory.evaluate_importance import EvaluateImportanceSkill
        from models.llm import LLMClient

        captured = {}
        mock_llm = MagicMock(spec=LLMClient)

        async def mock_generate(prompt, model, think, extra_options=None):
            captured["model"] = model
            response = _make_mock_llm_response(json.dumps({
                "importance_score": 0.6,
                "reasoning": "テスト",
                "topics": [],
            }))
            return response

        mock_llm.generate = mock_generate
        skill = EvaluateImportanceSkill(llm_client=mock_llm)

        await skill.run({
            "content": "テスト",
            "source": "test",
        })

        assert captured["model"] == "qwen3.5:4b"

    @pytest.mark.asyncio
    async def test_model_override_via_params(self):
        """params に model が指定された場合はそちらを優先"""
        from skills.memory.evaluate_importance import EvaluateImportanceSkill
        from models.llm import LLMClient

        captured = {}
        mock_llm = MagicMock(spec=LLMClient)

        async def mock_generate(prompt, model, think, extra_options=None):
            captured["model"] = model
            response = _make_mock_llm_response(json.dumps({
                "importance_score": 0.6,
                "reasoning": "テスト",
                "topics": [],
            }))
            return response

        mock_llm.generate = mock_generate
        skill = EvaluateImportanceSkill(llm_client=mock_llm)

        await skill.run({
            "content": "テスト",
            "source": "test",
            "model": "qwen3.5:14b",
        })

        assert captured["model"] == "qwen3.5:14b"

    @pytest.mark.asyncio
    async def test_topics_is_list(self):
        """topics フィールドはリスト型"""
        from skills.memory.evaluate_importance import EvaluateImportanceSkill

        llm_response_json = json.dumps({
            "importance_score": 0.75,
            "reasoning": "複数のトピックを含む",
            "topics": ["AI", "機械学習", "Python", "OSS"],
        })
        mock_llm = _make_llm_client_mock(llm_response_json)
        skill = EvaluateImportanceSkill(llm_client=mock_llm)

        result = await skill.run({
            "content": "機械学習の最新動向",
            "source": "arxiv",
        })

        assert isinstance(result["topics"], list)
        assert "AI" in result["topics"]

    @pytest.mark.asyncio
    async def test_context_passed_to_llm(self):
        """context が指定された場合は LLM プロンプトに含まれる"""
        from skills.memory.evaluate_importance import EvaluateImportanceSkill
        from models.llm import LLMClient

        captured = {}
        mock_llm = MagicMock(spec=LLMClient)

        async def mock_generate(prompt, model, think, extra_options=None):
            captured["prompt"] = prompt
            response = _make_mock_llm_response(json.dumps({
                "importance_score": 0.6,
                "reasoning": "テスト",
                "topics": [],
            }))
            return response

        mock_llm.generate = mock_generate
        skill = EvaluateImportanceSkill(llm_client=mock_llm)

        await skill.run({
            "content": "コンテンツ",
            "source": "test",
            "context": "エージェントは技術情報を重視している",
        })

        assert "エージェントは技術情報を重視している" in captured["prompt"]

    @pytest.mark.asyncio
    async def test_code_block_json_parsed(self):
        """LLM が ```json ブロックで返した場合もパースされる"""
        from skills.memory.evaluate_importance import EvaluateImportanceSkill

        llm_response = """以下の評価結果です:
```json
{
  "importance_score": 0.65,
  "reasoning": "コードブロック内のJSON",
  "topics": ["Go", "OSS"]
}
```"""
        mock_llm = _make_llm_client_mock(llm_response)
        skill = EvaluateImportanceSkill(llm_client=mock_llm)

        result = await skill.run({
            "content": "Go 言語の新機能",
            "source": "github_trending",
        })

        assert result["importance_score"] == 0.65
        assert "Go" in result["topics"]

    @pytest.mark.asyncio
    async def test_reasoning_is_string(self):
        """reasoning フィールドは文字列型"""
        from skills.memory.evaluate_importance import EvaluateImportanceSkill

        llm_response_json = json.dumps({
            "importance_score": 0.55,
            "reasoning": "技術的なコンテンツで有益",
            "topics": ["Docker"],
        })
        mock_llm = _make_llm_client_mock(llm_response_json)
        skill = EvaluateImportanceSkill(llm_client=mock_llm)

        result = await skill.run({
            "content": "Docker の新機能",
            "source": "blog",
        })

        assert isinstance(result["reasoning"], str)
        assert len(result["reasoning"]) > 0
