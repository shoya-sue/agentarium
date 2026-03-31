"""
tests/integration/test_llm_integration.py — Ollama LLM 統合テスト

LLMClient / llm_call Skill を実際の Ollama に対してテストする。

前提: Ollama が localhost:11434 で起動済み (qwen3.5:35b-a3b)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from tests.integration.conftest import OLLAMA_URL, requires_ollama


@requires_ollama
class TestLLMClientIntegration:
    """LLMClient を実際の Ollama に対してテストする"""

    def _make_client(self):
        """テスト用 LLMClient を生成する"""
        from models.llm import LLMClient
        return LLMClient(
            base_url=OLLAMA_URL,
            model="qwen3.5:35b-a3b",
            timeout_seconds=120,  # 他プロジェクトとの Ollama 競合を考慮して余裕を持たせる
        )

    @pytest.mark.asyncio
    async def test_basic_generation(self):
        """基本的なテキスト生成が動作する"""
        client = self._make_client()
        try:
            response = await client.generate(
                prompt="「こんにちは」と日本語で返してください。それだけでいいです。",
                think=False,
            )
            assert response.content is not None
            assert len(response.content) > 0
            assert response.eval_count > 0
            assert response.tokens_per_second > 0
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_json_output_generation(self):
        """JSON 形式の出力を正しく生成・パースできる"""
        client = self._make_client()
        try:
            prompt = (
                "以下の情報をJSONとして返してください。他の文字は不要です。\n"
                '{"title": "テスト", "score": 0.9, "tags": ["AI", "test"]}'
                "\nこの内容をそのまま JSON として出力してください。"
            )
            response = await client.generate(prompt=prompt, think=False)

            # JSON パースを試みる
            data = response.parse_json()
            assert isinstance(data, dict)
            # title フィールドが含まれていれば OK
            assert "title" in data or len(data) > 0

        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_performance_metrics(self):
        """パフォーマンス指標が適切な範囲にある"""
        client = self._make_client()
        try:
            response = await client.generate(
                prompt="1+1の答えを数字だけで答えてください。",
                think=False,
            )
            # Phase 0 V1 検証結果: think=false で 31.9 tok/s（単独実行時）
            # 他プロジェクトが Ollama を同時利用している場合は低下するため
            # 最低ライン 1 tok/s を確認（生成が正常に動いていることの確認）
            assert response.tokens_per_second > 1.0, (
                f"LLM速度が遅すぎます: {response.tokens_per_second:.1f} tok/s"
            )
            # eval_duration が記録されている
            assert response.eval_duration_ns > 0
        finally:
            await client.close()


@requires_ollama
class TestLLMCallSkillIntegration:
    """llm_call Skill を実際の Ollama に対してテストする"""

    @pytest.mark.asyncio
    async def test_llm_call_skill_basic(self):
        """llm_call Skill が基本的なプロンプトに応答する"""
        from skills.reasoning.llm_call import LlmCallSkill
        from models.llm import LLMClient

        client = LLMClient(
            base_url=OLLAMA_URL,
            model="qwen3.5:35b-a3b",
            timeout_seconds=120,
        )
        skill = LlmCallSkill(llm_client=client)

        try:
            result = await skill.run({
                "messages": [
                    {"role": "user", "content": "「テスト完了」と返してください"}
                ],
                "model": "qwen3.5:35b-a3b",
            })

            # result は {"content": str, "model": str, "tokens_used": {...}} の dict
            assert isinstance(result, dict)
            assert "content" in result
            assert len(result["content"]) > 0
            assert "tokens_used" in result
        finally:
            await client.close()
