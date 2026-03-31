"""
tests/test_parse_llm_output.py — ParseLlmOutputSkill ユニットテスト

JSON パース戦略（direct_json / extract_code_block / extract_first_object）
とフォールバック動作を検証する。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestParseLlmOutputSkill:
    """ParseLlmOutputSkill の動作検証"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.reasoning.parse_llm_output import ParseLlmOutputSkill
        assert ParseLlmOutputSkill is not None

    @pytest.mark.asyncio
    async def test_direct_json_object(self):
        """純粋な JSON オブジェクト文字列を直接パースできる"""
        from skills.reasoning.parse_llm_output import ParseLlmOutputSkill
        skill = ParseLlmOutputSkill()
        result = await skill.run({"raw_text": '{"key": "value", "num": 42}'})
        assert result["success"] is True
        assert result["strategy_used"] == "direct_json"
        assert result["parsed"] == {"key": "value", "num": 42}

    @pytest.mark.asyncio
    async def test_direct_json_array(self):
        """純粋な JSON 配列文字列を直接パースできる"""
        from skills.reasoning.parse_llm_output import ParseLlmOutputSkill
        skill = ParseLlmOutputSkill()
        result = await skill.run({"raw_text": '[{"a": 1}, {"b": 2}]'})
        assert result["success"] is True
        assert result["strategy_used"] == "direct_json"
        assert result["parsed"] == [{"a": 1}, {"b": 2}]

    @pytest.mark.asyncio
    async def test_extract_code_block(self):
        """```json コードブロックからパースできる"""
        from skills.reasoning.parse_llm_output import ParseLlmOutputSkill
        skill = ParseLlmOutputSkill()
        raw = '以下が結果です:\n```json\n{"items": [1, 2, 3]}\n```\nありがとう。'
        result = await skill.run({"raw_text": raw})
        assert result["success"] is True
        assert result["strategy_used"] == "extract_code_block"
        assert result["parsed"] == {"items": [1, 2, 3]}

    @pytest.mark.asyncio
    async def test_extract_code_block_without_lang(self):
        """``` コードブロック（言語指定なし）からパースできる"""
        from skills.reasoning.parse_llm_output import ParseLlmOutputSkill
        skill = ParseLlmOutputSkill()
        raw = 'Here:\n```\n{"x": true}\n```'
        result = await skill.run({"raw_text": raw})
        assert result["success"] is True
        assert result["parsed"] == {"x": True}

    @pytest.mark.asyncio
    async def test_extract_first_object(self):
        """テキスト中の最初の JSON オブジェクトを抽出できる"""
        from skills.reasoning.parse_llm_output import ParseLlmOutputSkill
        skill = ParseLlmOutputSkill()
        raw = 'The result is {"score": 0.95, "label": "positive"} as shown.'
        result = await skill.run({"raw_text": raw})
        assert result["success"] is True
        assert result["strategy_used"] == "extract_first_object"
        assert result["parsed"]["score"] == pytest.approx(0.95)

    @pytest.mark.asyncio
    async def test_fallback_value_on_failure(self):
        """パース失敗時に fallback_value が返る"""
        from skills.reasoning.parse_llm_output import ParseLlmOutputSkill
        skill = ParseLlmOutputSkill()
        result = await skill.run({
            "raw_text": "これはJSONではありません",
            "fallback_value": {"error": "parse_failed"},
        })
        assert result["success"] is False
        assert result["parsed"] == {"error": "parse_failed"}

    @pytest.mark.asyncio
    async def test_no_fallback_raises_value_error(self):
        """fallback_value なしでパース失敗すると ValueError が発生"""
        from skills.reasoning.parse_llm_output import ParseLlmOutputSkill
        skill = ParseLlmOutputSkill()
        with pytest.raises(ValueError, match="JSON 抽出に失敗"):
            await skill.run({"raw_text": "これはJSONではありません"})

    @pytest.mark.asyncio
    async def test_result_contains_required_fields(self):
        """成功時の結果に必須フィールドが含まれる"""
        from skills.reasoning.parse_llm_output import ParseLlmOutputSkill
        skill = ParseLlmOutputSkill()
        result = await skill.run({"raw_text": '{"ok": true}'})
        assert "parsed" in result
        assert "success" in result
        assert "strategy_used" in result

    @pytest.mark.asyncio
    async def test_whitespace_around_json(self):
        """前後の空白・改行を除去してパースできる"""
        from skills.reasoning.parse_llm_output import ParseLlmOutputSkill
        skill = ParseLlmOutputSkill()
        result = await skill.run({"raw_text": '  \n  {"trimmed": true}  \n  '})
        assert result["success"] is True
        assert result["parsed"] == {"trimmed": True}
