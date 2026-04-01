"""
tests/test_generate_topic_report.py — GenerateTopicReportSkill ユニットテスト

特定トピックの深掘りレポートを生成する Skill の意思決定ロジックを検証する。
dry_run モードで LLM を呼び出さずにロジックをテストする。
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestGenerateTopicReportImport:
    """インポートとクラス構造の確認"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.output.generate_topic_report import GenerateTopicReportSkill
        assert GenerateTopicReportSkill is not None

    def test_instantiate(self):
        """インスタンス化できる（LLMClient 不要）"""
        from skills.output.generate_topic_report import GenerateTopicReportSkill
        skill = GenerateTopicReportSkill(llm_client=None)
        assert skill is not None

    def test_has_run_method(self):
        """run メソッドが存在する"""
        from skills.output.generate_topic_report import GenerateTopicReportSkill
        skill = GenerateTopicReportSkill(llm_client=None)
        assert callable(skill.run)


class TestGenerateTopicReportDryRun:
    """dry_run モードの検証（LLM 不要）"""

    def test_dry_run_returns_generated_false(self):
        """dry_run=True のとき generated が False である"""
        from skills.output.generate_topic_report import GenerateTopicReportSkill
        skill = GenerateTopicReportSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "topic": "Rust",
                "entries": [{"title": "Rust 2024", "summary": "Rust is fast"}],
                "dry_run": True,
            })
        )
        assert result["generated"] is False

    def test_dry_run_returns_dry_run_true(self):
        """dry_run=True のとき dry_run フラグが True である"""
        from skills.output.generate_topic_report import GenerateTopicReportSkill
        skill = GenerateTopicReportSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "topic": "Python",
                "entries": [{"title": "PEP 703"}],
                "dry_run": True,
            })
        )
        assert result["dry_run"] is True

    def test_dry_run_returns_reason_dry_run(self):
        """dry_run=True のとき reason が dry_run である"""
        from skills.output.generate_topic_report import GenerateTopicReportSkill
        skill = GenerateTopicReportSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "topic": "AI",
                "entries": [{"title": "GPT-5"}],
                "dry_run": True,
            })
        )
        assert result["reason"] == "dry_run"

    def test_dry_run_returns_entry_count(self):
        """dry_run=True のとき entry_count が返される"""
        from skills.output.generate_topic_report import GenerateTopicReportSkill
        skill = GenerateTopicReportSkill(llm_client=None)
        entries = [{"title": f"Article {i}"} for i in range(7)]
        result = asyncio.run(
            skill.run({
                "topic": "Blockchain",
                "entries": entries,
                "dry_run": True,
            })
        )
        assert result["entry_count"] == 7


class TestGenerateTopicReportOutputSchema:
    """出力スキーマの検証"""

    def test_output_has_required_fields(self):
        """出力に必須フィールドが含まれる"""
        from skills.output.generate_topic_report import GenerateTopicReportSkill
        skill = GenerateTopicReportSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "topic": "Rust",
                "entries": [{"title": "Item 1"}],
                "dry_run": True,
            })
        )
        assert "generated" in result
        assert "topic" in result
        assert "title" in result
        assert "body" in result
        assert "entry_count" in result
        assert "dry_run" in result

    def test_topic_is_echoed_back(self):
        """入力 topic が出力にエコーバックされる"""
        from skills.output.generate_topic_report import GenerateTopicReportSkill
        skill = GenerateTopicReportSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "topic": "WebAssembly",
                "entries": [{"title": "Wasm 2.0"}],
                "dry_run": True,
            })
        )
        assert result["topic"] == "WebAssembly"

    def test_generated_is_bool(self):
        """generated フィールドが bool 型である"""
        from skills.output.generate_topic_report import GenerateTopicReportSkill
        skill = GenerateTopicReportSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "topic": "AI",
                "entries": [{"title": "Item"}],
                "dry_run": True,
            })
        )
        assert isinstance(result["generated"], bool)


class TestGenerateTopicReportValidation:
    """入力バリデーションの検証"""

    def test_empty_entries_returns_not_generated(self):
        """エントリが空のとき生成をスキップする"""
        from skills.output.generate_topic_report import GenerateTopicReportSkill
        skill = GenerateTopicReportSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "topic": "Rust",
                "entries": [],
                "dry_run": False,
            })
        )
        assert result["generated"] is False
        assert result["reason"] == "empty_entries"

    def test_empty_topic_returns_not_generated(self):
        """topic が空のとき生成をスキップする"""
        from skills.output.generate_topic_report import GenerateTopicReportSkill
        skill = GenerateTopicReportSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "topic": "",
                "entries": [{"title": "Item"}],
                "dry_run": False,
            })
        )
        assert result["generated"] is False
        assert result["reason"] == "empty_topic"

    def test_missing_topic_returns_not_generated(self):
        """topic が None のとき生成をスキップする"""
        from skills.output.generate_topic_report import GenerateTopicReportSkill
        skill = GenerateTopicReportSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "topic": None,
                "entries": [{"title": "Item"}],
                "dry_run": False,
            })
        )
        assert result["generated"] is False
        assert result["reason"] == "empty_topic"


class TestGenerateTopicReportLLMMock:
    """LLM モックを使った生成ロジックの検証"""

    def test_llm_success_returns_generated_true(self):
        """LLM 呼び出し成功時に generated=True が返る"""
        from skills.output.generate_topic_report import GenerateTopicReportSkill

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "# Rust Report\n\n## Overview\n\nRust is a systems programming language..."
        mock_llm.generate = AsyncMock(return_value=mock_response)

        skill = GenerateTopicReportSkill(llm_client=mock_llm)
        result = asyncio.run(
            skill.run({
                "topic": "Rust",
                "entries": [{"title": "Rust 2024", "summary": "Rust performance improvements"}],
                "dry_run": False,
            })
        )
        assert result["generated"] is True
        assert result["body"] != ""

    def test_llm_failure_returns_fallback(self):
        """LLM エラー時に generated=False でフォールバックを返す"""
        from skills.output.generate_topic_report import GenerateTopicReportSkill

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(side_effect=Exception("Connection refused"))

        skill = GenerateTopicReportSkill(llm_client=mock_llm)
        result = asyncio.run(
            skill.run({
                "topic": "AI",
                "entries": [{"title": "ChatGPT update"}],
                "dry_run": False,
            })
        )
        assert result["generated"] is False
        assert "reason" in result

    def test_llm_receives_topic_in_prompt(self):
        """LLM にトピック名が渡される"""
        from skills.output.generate_topic_report import GenerateTopicReportSkill

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "# Report"
        mock_llm.generate = AsyncMock(return_value=mock_response)

        skill = GenerateTopicReportSkill(llm_client=mock_llm)
        asyncio.run(
            skill.run({
                "topic": "WebAssembly",
                "entries": [{"title": "Wasm WASI 2.0", "summary": "WASI improvements"}],
                "dry_run": False,
            })
        )
        assert mock_llm.generate.called
        call_kwargs = mock_llm.generate.call_args
        prompt = call_kwargs[1].get("prompt") or call_kwargs[0][0]
        assert "WebAssembly" in prompt
