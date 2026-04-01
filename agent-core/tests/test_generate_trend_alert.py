"""
tests/test_generate_trend_alert.py — GenerateTrendAlertSkill ユニットテスト

急上昇トピック・異常値の通知テキストを生成する Skill の意思決定ロジックを検証する。
dry_run モードで LLM を呼び出さずにロジックをテストする。
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestGenerateTrendAlertImport:
    """インポートとクラス構造の確認"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.output.generate_trend_alert import GenerateTrendAlertSkill
        assert GenerateTrendAlertSkill is not None

    def test_instantiate(self):
        """インスタンス化できる（LLMClient 不要）"""
        from skills.output.generate_trend_alert import GenerateTrendAlertSkill
        skill = GenerateTrendAlertSkill(llm_client=None)
        assert skill is not None

    def test_has_run_method(self):
        """run メソッドが存在する"""
        from skills.output.generate_trend_alert import GenerateTrendAlertSkill
        skill = GenerateTrendAlertSkill(llm_client=None)
        assert callable(skill.run)

    def test_min_alert_score_constant(self):
        """MIN_ALERT_SCORE 定数が存在する"""
        from skills.output.generate_trend_alert import MIN_ALERT_SCORE
        assert isinstance(MIN_ALERT_SCORE, (int, float))


class TestGenerateTrendAlertDryRun:
    """dry_run モードの検証（LLM 不要）"""

    def test_dry_run_returns_generated_false(self):
        """dry_run=True のとき generated が False である"""
        from skills.output.generate_trend_alert import GenerateTrendAlertSkill
        skill = GenerateTrendAlertSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "topic": "Rust",
                "score": 0.9,
                "entries": [{"title": "Rust trending"}],
                "dry_run": True,
            })
        )
        assert result["generated"] is False

    def test_dry_run_returns_dry_run_true(self):
        """dry_run=True のとき dry_run フラグが True である"""
        from skills.output.generate_trend_alert import GenerateTrendAlertSkill
        skill = GenerateTrendAlertSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "topic": "AI",
                "score": 0.85,
                "entries": [{"title": "GPT trending"}],
                "dry_run": True,
            })
        )
        assert result["dry_run"] is True

    def test_dry_run_returns_reason_dry_run(self):
        """dry_run=True のとき reason が dry_run である"""
        from skills.output.generate_trend_alert import GenerateTrendAlertSkill
        skill = GenerateTrendAlertSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "topic": "Python",
                "score": 0.75,
                "entries": [{"title": "Python 4.0"}],
                "dry_run": True,
            })
        )
        assert result["reason"] == "dry_run"


class TestGenerateTrendAlertOutputSchema:
    """出力スキーマの検証"""

    def test_output_has_required_fields(self):
        """出力に必須フィールドが含まれる"""
        from skills.output.generate_trend_alert import GenerateTrendAlertSkill
        skill = GenerateTrendAlertSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "topic": "Rust",
                "score": 0.9,
                "entries": [{"title": "Item"}],
                "dry_run": True,
            })
        )
        assert "generated" in result
        assert "topic" in result
        assert "score" in result
        assert "alert_text" in result
        assert "entry_count" in result
        assert "dry_run" in result

    def test_topic_is_echoed_back(self):
        """入力 topic が出力にエコーバックされる"""
        from skills.output.generate_trend_alert import GenerateTrendAlertSkill
        skill = GenerateTrendAlertSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "topic": "WebGPU",
                "score": 0.8,
                "entries": [{"title": "WebGPU launch"}],
                "dry_run": True,
            })
        )
        assert result["topic"] == "WebGPU"

    def test_score_is_echoed_back(self):
        """入力 score が出力にエコーバックされる"""
        from skills.output.generate_trend_alert import GenerateTrendAlertSkill
        skill = GenerateTrendAlertSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "topic": "Rust",
                "score": 0.95,
                "entries": [{"title": "Item"}],
                "dry_run": True,
            })
        )
        assert result["score"] == 0.95

    def test_generated_is_bool(self):
        """generated フィールドが bool 型である"""
        from skills.output.generate_trend_alert import GenerateTrendAlertSkill
        skill = GenerateTrendAlertSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "topic": "AI",
                "score": 0.9,
                "entries": [{"title": "Item"}],
                "dry_run": True,
            })
        )
        assert isinstance(result["generated"], bool)


class TestGenerateTrendAlertValidation:
    """入力バリデーションの検証"""

    def test_score_below_threshold_returns_not_generated(self):
        """スコアが閾値未満のとき生成をスキップする"""
        from skills.output.generate_trend_alert import GenerateTrendAlertSkill, MIN_ALERT_SCORE
        skill = GenerateTrendAlertSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "topic": "Rust",
                "score": MIN_ALERT_SCORE - 0.01,
                "entries": [{"title": "Item"}],
                "dry_run": False,
            })
        )
        assert result["generated"] is False
        assert result["reason"] == "score_below_threshold"

    def test_empty_entries_returns_not_generated(self):
        """エントリが空のとき生成をスキップする"""
        from skills.output.generate_trend_alert import GenerateTrendAlertSkill
        skill = GenerateTrendAlertSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "topic": "Rust",
                "score": 0.9,
                "entries": [],
                "dry_run": False,
            })
        )
        assert result["generated"] is False
        assert result["reason"] == "empty_entries"

    def test_empty_topic_returns_not_generated(self):
        """topic が空のとき生成をスキップする"""
        from skills.output.generate_trend_alert import GenerateTrendAlertSkill
        skill = GenerateTrendAlertSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "topic": "",
                "score": 0.9,
                "entries": [{"title": "Item"}],
                "dry_run": False,
            })
        )
        assert result["generated"] is False
        assert result["reason"] == "empty_topic"

    def test_score_exactly_at_threshold_passes_validation(self):
        """スコアが閾値ちょうどのときはバリデーションを通過する（スキップしない）"""
        from skills.output.generate_trend_alert import GenerateTrendAlertSkill, MIN_ALERT_SCORE
        skill = GenerateTrendAlertSkill(llm_client=None)
        result = asyncio.run(
            skill.run({
                "topic": "Rust",
                "score": MIN_ALERT_SCORE,
                "entries": [{"title": "Item"}],
                "dry_run": True,  # dry_run で LLM スキップ
            })
        )
        assert result.get("reason") != "score_below_threshold"


class TestGenerateTrendAlertLLMMock:
    """LLM モックを使った生成ロジックの検証"""

    def test_llm_success_returns_generated_true(self):
        """LLM 呼び出し成功時に generated=True が返る"""
        from skills.output.generate_trend_alert import GenerateTrendAlertSkill

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "🚨 トレンドアラート: Rust が急上昇中！"
        mock_llm.generate = AsyncMock(return_value=mock_response)

        skill = GenerateTrendAlertSkill(llm_client=mock_llm)
        result = asyncio.run(
            skill.run({
                "topic": "Rust",
                "score": 0.9,
                "entries": [{"title": "Rust 2024", "summary": "Rust performance improvements"}],
                "dry_run": False,
            })
        )
        assert result["generated"] is True
        assert result["alert_text"] != ""

    def test_llm_failure_returns_fallback(self):
        """LLM エラー時に generated=False でフォールバックを返す"""
        from skills.output.generate_trend_alert import GenerateTrendAlertSkill

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(side_effect=Exception("Timeout"))

        skill = GenerateTrendAlertSkill(llm_client=mock_llm)
        result = asyncio.run(
            skill.run({
                "topic": "AI",
                "score": 0.95,
                "entries": [{"title": "GPT trending"}],
                "dry_run": False,
            })
        )
        assert result["generated"] is False
        assert "reason" in result

    def test_llm_receives_topic_and_score_in_prompt(self):
        """LLM にトピック名とスコアが渡される"""
        from skills.output.generate_trend_alert import GenerateTrendAlertSkill

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Alert!"
        mock_llm.generate = AsyncMock(return_value=mock_response)

        skill = GenerateTrendAlertSkill(llm_client=mock_llm)
        asyncio.run(
            skill.run({
                "topic": "Quantum Computing",
                "score": 0.87,
                "entries": [{"title": "IBM Quantum 1000 qubits"}],
                "dry_run": False,
            })
        )
        assert mock_llm.generate.called
        call_kwargs = mock_llm.generate.call_args
        prompt = call_kwargs[1].get("prompt") or call_kwargs[0][0]
        assert "Quantum Computing" in prompt
