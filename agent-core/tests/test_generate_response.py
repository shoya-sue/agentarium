"""
tests/test_generate_response.py — GenerateResponseSkill ユニットテスト

LLMClient をモックしてキャラクター応答生成ロジックを検証する。
"""

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


def _make_llm_client_mock(
    response_content: str,
    model: str = "qwen3.5:14b",
) -> MagicMock:
    """LLMClient のモックを作成する。"""
    from models.llm import LLMClient
    mock_llm = MagicMock(spec=LLMClient)
    mock_response = _make_mock_llm_response(response_content, model)
    mock_llm.generate = AsyncMock(return_value=mock_response)
    return mock_llm


def _sample_persona_context(character_name: str = "zephyr") -> dict:
    """テスト用 BuildPersonaContextSkill の出力サンプルを返す。"""
    return {
        "persona_prompt": (
            f"あなたは {character_name} という AI Agent です。\n"
            "好奇心旺盛で、技術トピックに詳しいキャラクターです。"
        ),
        "style_instructions": (
            "【スタイル指示】\n"
            "  - 一人称: 「わたし」を使用する\n"
            "  - トーン: フレンドリーで知的"
        ),
        "motivation_context": "【現在のモチベーション】\n  - 主目標: 情報を共有する",
        "character_name": character_name,
        "token_count": 42,
    }


class TestGenerateResponseSkill:
    """GenerateResponseSkill の動作検証"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.reasoning.generate_response import GenerateResponseSkill
        assert GenerateResponseSkill is not None

    @pytest.mark.asyncio
    async def test_returns_response_dict(self):
        """正常ケース: LLM がテキストを返す → 必要フィールドが全て存在する"""
        from skills.reasoning.generate_response import GenerateResponseSkill

        mock_llm = _make_llm_client_mock("こんにちは！最近のAI動向について話しましょうか。")
        skill = GenerateResponseSkill(llm_client=mock_llm)

        result = await skill.run({
            "persona_context": _sample_persona_context(),
            "trigger": "最近のAI動向について話して",
        })

        assert "response_text" in result
        assert "character_name" in result
        assert "platform" in result
        assert "model_used" in result
        assert "token_estimate" in result

    @pytest.mark.asyncio
    async def test_empty_response_on_llm_error(self):
        """LLM エラー → response_text = '' を返す"""
        from skills.reasoning.generate_response import GenerateResponseSkill
        from models.llm import LLMClient

        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.generate = AsyncMock(side_effect=Exception("接続エラー"))
        skill = GenerateResponseSkill(llm_client=mock_llm)

        result = await skill.run({
            "persona_context": _sample_persona_context(),
            "trigger": "テストメッセージ",
        })

        assert result["response_text"] == ""

    @pytest.mark.asyncio
    async def test_raises_on_missing_persona_prompt(self):
        """persona_context に persona_prompt なし → ValueError を raise する"""
        from skills.reasoning.generate_response import GenerateResponseSkill

        mock_llm = _make_llm_client_mock("テスト応答")
        skill = GenerateResponseSkill(llm_client=mock_llm)

        # persona_prompt キーなしの persona_context
        invalid_persona = {
            "style_instructions": "スタイル指示",
            "character_name": "zephyr",
        }

        with pytest.raises(ValueError):
            await skill.run({
                "persona_context": invalid_persona,
                "trigger": "テストメッセージ",
            })

    @pytest.mark.asyncio
    async def test_platform_defaults_to_discord(self):
        """platform 未指定 → デフォルトで 'discord' になる"""
        from skills.reasoning.generate_response import GenerateResponseSkill

        mock_llm = _make_llm_client_mock("Discord向け応答")
        skill = GenerateResponseSkill(llm_client=mock_llm)

        result = await skill.run({
            "persona_context": _sample_persona_context(),
            "trigger": "テストメッセージ",
            # platform は指定しない
        })

        assert result["platform"] == "discord"

    @pytest.mark.asyncio
    async def test_token_estimate_calculated(self):
        """token_estimate = len(response_text) // 4"""
        from skills.reasoning.generate_response import GenerateResponseSkill

        response_text = "a" * 40  # 40文字 → token_estimate = 10
        mock_llm = _make_llm_client_mock(response_text)
        skill = GenerateResponseSkill(llm_client=mock_llm)

        result = await skill.run({
            "persona_context": _sample_persona_context(),
            "trigger": "テストメッセージ",
        })

        assert result["token_estimate"] == 40 // 4

    @pytest.mark.asyncio
    async def test_character_name_extracted(self):
        """persona_context の character_name が result に入る"""
        from skills.reasoning.generate_response import GenerateResponseSkill

        mock_llm = _make_llm_client_mock("テスト応答")
        skill = GenerateResponseSkill(llm_client=mock_llm)

        result = await skill.run({
            "persona_context": _sample_persona_context(character_name="lynx"),
            "trigger": "テストメッセージ",
        })

        assert result["character_name"] == "lynx"

    @pytest.mark.asyncio
    async def test_model_used_in_result(self):
        """model_used フィールドが結果に含まれる"""
        from skills.reasoning.generate_response import GenerateResponseSkill

        mock_llm = _make_llm_client_mock("テスト応答")
        skill = GenerateResponseSkill(llm_client=mock_llm)

        result = await skill.run({
            "persona_context": _sample_persona_context(),
            "trigger": "テストメッセージ",
        })

        assert "model_used" in result
        assert isinstance(result["model_used"], str)
        assert len(result["model_used"]) > 0

    @pytest.mark.asyncio
    async def test_platform_x_applied(self):
        """platform='x' を指定した場合、platform が 'x' になる"""
        from skills.reasoning.generate_response import GenerateResponseSkill

        mock_llm = _make_llm_client_mock("X向け短い応答")
        skill = GenerateResponseSkill(llm_client=mock_llm)

        result = await skill.run({
            "persona_context": _sample_persona_context(),
            "trigger": "テストメッセージ",
            "platform": "x",
        })

        assert result["platform"] == "x"

    @pytest.mark.asyncio
    async def test_model_override_via_params(self):
        """params に model が指定された場合はそちらを優先する"""
        from skills.reasoning.generate_response import GenerateResponseSkill
        from models.llm import LLMClient

        captured: dict = {}
        mock_llm = MagicMock(spec=LLMClient)

        async def mock_generate(prompt: str, model: str, think: bool, extra_options=None):
            captured["model"] = model
            return _make_mock_llm_response("テスト応答")

        mock_llm.generate = mock_generate
        skill = GenerateResponseSkill(llm_client=mock_llm)

        result = await skill.run({
            "persona_context": _sample_persona_context(),
            "trigger": "テストメッセージ",
            "model": "qwen3.5:4b",
        })

        assert result["model_used"] == "qwen3.5:4b"
        assert captured.get("model") == "qwen3.5:4b"

    @pytest.mark.asyncio
    async def test_token_estimate_zero_on_empty_response(self):
        """LLM エラーで response_text = '' の場合 token_estimate = 0"""
        from skills.reasoning.generate_response import GenerateResponseSkill
        from models.llm import LLMClient

        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.generate = AsyncMock(side_effect=Exception("タイムアウト"))
        skill = GenerateResponseSkill(llm_client=mock_llm)

        result = await skill.run({
            "persona_context": _sample_persona_context(),
            "trigger": "テストメッセージ",
        })

        assert result["token_estimate"] == 0
