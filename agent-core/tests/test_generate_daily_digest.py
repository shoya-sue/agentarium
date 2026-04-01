"""
tests/test_generate_daily_digest.py — GenerateDailyDigestSkill ユニットテスト

1日の収集情報・活動サマリーを生成する Skill の意思決定ロジックを検証する。
dry_run モードで LLM を呼び出さずにロジックをテストする。
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestGenerateDailyDigestImport:
    """インポートとクラス構造の確認"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.output.generate_daily_digest import GenerateDailyDigestSkill
        assert GenerateDailyDigestSkill is not None

    def test_instantiate(self):
        """インスタンス化できる（LLMClient 不要）"""
        from skills.output.generate_daily_digest import GenerateDailyDigestSkill
        skill = GenerateDailyDigestSkill(llm_client=None)
        assert skill is not None

    def test_has_run_method(self):
        """run メソッドが存在する"""
        from skills.output.generate_daily_digest import GenerateDailyDigestSkill
        skill = GenerateDailyDigestSkill(llm_client=None)
        assert callable(skill.run)


class TestGenerateDailyDigestDryRun:
    """dry_run モードの検証（LLM 不要）"""

    def test_dry_run_returns_generated_false(self):
        """dry_run=True のとき generated が False である"""
        from skills.output.generate_daily_digest import GenerateDailyDigestSkill
        skill = GenerateDailyDigestSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "entries": [{"title": "Item 1", "summary": "Summary 1"}],
                "date": "2026-04-01",
                "dry_run": True,
            })
        )
        assert result["generated"] is False

    def test_dry_run_returns_dry_run_true(self):
        """dry_run=True のとき dry_run フラグが True である"""
        from skills.output.generate_daily_digest import GenerateDailyDigestSkill
        skill = GenerateDailyDigestSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "entries": [{"title": "Item 1", "summary": "Summary 1"}],
                "date": "2026-04-01",
                "dry_run": True,
            })
        )
        assert result["dry_run"] is True

    def test_dry_run_returns_reason_dry_run(self):
        """dry_run=True のとき reason が dry_run である"""
        from skills.output.generate_daily_digest import GenerateDailyDigestSkill
        skill = GenerateDailyDigestSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "entries": [{"title": "Item 1"}],
                "date": "2026-04-01",
                "dry_run": True,
            })
        )
        assert result["reason"] == "dry_run"

    def test_dry_run_returns_entry_count(self):
        """dry_run=True のとき entry_count が返される"""
        from skills.output.generate_daily_digest import GenerateDailyDigestSkill
        skill = GenerateDailyDigestSkill(llm_client=None)
        entries = [{"title": f"Item {i}"} for i in range(5)]
        result = asyncio.run(
            skill.run({
                "entries": entries,
                "date": "2026-04-01",
                "dry_run": True,
            })
        )
        assert result["entry_count"] == 5


class TestGenerateDailyDigestOutputSchema:
    """出力スキーマの検証"""

    def test_output_has_required_fields(self):
        """出力に必須フィールドが含まれる"""
        from skills.output.generate_daily_digest import GenerateDailyDigestSkill
        skill = GenerateDailyDigestSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "entries": [{"title": "Item 1"}],
                "date": "2026-04-01",
                "dry_run": True,
            })
        )
        assert "generated" in result
        assert "title" in result
        assert "body" in result
        assert "entry_count" in result
        assert "date" in result
        assert "dry_run" in result

    def test_date_is_echoed_back(self):
        """入力 date が出力にエコーバックされる"""
        from skills.output.generate_daily_digest import GenerateDailyDigestSkill
        skill = GenerateDailyDigestSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "entries": [],
                "date": "2026-04-01",
                "dry_run": True,
            })
        )
        assert result["date"] == "2026-04-01"

    def test_generated_is_bool(self):
        """generated フィールドが bool 型である"""
        from skills.output.generate_daily_digest import GenerateDailyDigestSkill
        skill = GenerateDailyDigestSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "entries": [],
                "date": "2026-04-01",
                "dry_run": True,
            })
        )
        assert isinstance(result["generated"], bool)

    def test_entry_count_is_int(self):
        """entry_count が int 型である"""
        from skills.output.generate_daily_digest import GenerateDailyDigestSkill
        skill = GenerateDailyDigestSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "entries": [{"title": "a"}, {"title": "b"}],
                "date": "2026-04-01",
                "dry_run": True,
            })
        )
        assert isinstance(result["entry_count"], int)


class TestGenerateDailyDigestValidation:
    """入力バリデーションの検証"""

    def test_empty_entries_returns_not_generated(self):
        """エントリが空のとき生成をスキップする"""
        from skills.output.generate_daily_digest import GenerateDailyDigestSkill
        skill = GenerateDailyDigestSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "entries": [],
                "date": "2026-04-01",
                "dry_run": False,
            })
        )
        assert result["generated"] is False
        assert result["reason"] == "empty_entries"

    def test_missing_date_uses_today(self):
        """date が未指定のとき today が使われる（エラーにならない）"""
        from skills.output.generate_daily_digest import GenerateDailyDigestSkill
        skill = GenerateDailyDigestSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "entries": [{"title": "Item"}],
                "dry_run": True,
            })
        )
        assert "date" in result
        assert result["date"] != ""


class TestGenerateDailyDigestLLMMock:
    """LLM モックを使った生成ロジックの検証"""

    def test_llm_success_returns_generated_true(self):
        """LLM 呼び出し成功時に generated=True が返る"""
        from skills.output.generate_daily_digest import GenerateDailyDigestSkill

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "# Daily Digest\n\nToday's summary..."
        mock_llm.generate = AsyncMock(return_value=mock_response)

        skill = GenerateDailyDigestSkill(llm_client=mock_llm)
        result = asyncio.run(
            skill.run({
                "entries": [{"title": "Item 1", "summary": "Summary 1"}],
                "date": "2026-04-01",
                "dry_run": False,
            })
        )
        assert result["generated"] is True
        assert result["body"] != ""

    def test_llm_failure_returns_fallback(self):
        """LLM エラー時に generated=False でフォールバックを返す"""
        from skills.output.generate_daily_digest import GenerateDailyDigestSkill

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(side_effect=Exception("LLM error"))

        skill = GenerateDailyDigestSkill(llm_client=mock_llm)
        result = asyncio.run(
            skill.run({
                "entries": [{"title": "Item 1"}],
                "date": "2026-04-01",
                "dry_run": False,
            })
        )
        assert result["generated"] is False
        assert "reason" in result

    def test_llm_receives_entry_titles_in_prompt(self):
        """LLM にエントリのタイトルが渡される"""
        from skills.output.generate_daily_digest import GenerateDailyDigestSkill

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "# Digest"
        mock_llm.generate = AsyncMock(return_value=mock_response)

        skill = GenerateDailyDigestSkill(llm_client=mock_llm)
        asyncio.run(
            skill.run({
                "entries": [{"title": "Rust is fast", "summary": "Rust performance summary"}],
                "date": "2026-04-01",
                "dry_run": False,
            })
        )
        # generate が呼ばれていることを確認
        assert mock_llm.generate.called
        call_kwargs = mock_llm.generate.call_args
        prompt = call_kwargs[1].get("prompt") or call_kwargs[0][0]
        assert "Rust is fast" in prompt
