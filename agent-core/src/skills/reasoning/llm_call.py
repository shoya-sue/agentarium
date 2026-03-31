"""
skills/reasoning/llm_call.py — LLM 呼び出し Skill

Ollama API への統一エントリポイント。
resolve_prompt が生成した messages 配列を受け取り、LLM レスポンスを返す。

Phase 0 V1 検証結果: think=false で安定動作（31.9 tok/s）
全呼び出しで think=false がデフォルト（routing.yaml と一致）。

Skill 入出力スキーマ: config/skills/reasoning/llm_call.yaml
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from models.llm import LLMClient

logger = logging.getLogger(__name__)

# messages を 1 つのプロンプト文字列に変換する際のロールプレフィックス
_ROLE_PREFIX: dict[str, str] = {
    "system": "System",
    "user": "User",
    "assistant": "Assistant",
}


def _messages_to_prompt(messages: list[dict[str, str]]) -> str:
    """
    OpenAI 互換 messages 配列を Ollama generate API 用の単一プロンプトに変換する。

    Phase 1 は /api/generate を使用（/api/chat は Phase 2 で検討）。

    Args:
        messages: [{"role": "system" | "user" | "assistant", "content": str}]

    Returns:
        "System: ...\n\nUser: ..." 形式の文字列
    """
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        prefix = _ROLE_PREFIX.get(role, role.capitalize())
        parts.append(f"{prefix}: {content}")
    return "\n\n".join(parts)


class LlmCallSkill:
    """
    llm_call Skill の実装。

    messages 配列を受け取り、Ollama で推論してレスポンスを返す。
    モデルは routing.yaml のデフォルトを使用（params.model で上書き可能）。
    """

    def __init__(
        self,
        llm_client: LLMClient,
        config_dir: Path | str | None = None,
    ) -> None:
        self._llm = llm_client
        if config_dir is None:
            config_dir = Path(__file__).parent.parent.parent.parent.parent / "config"
        self._config_dir = Path(config_dir)
        self._routing = self._load_routing()

    def _load_routing(self) -> dict[str, Any]:
        """config/llm/routing.yaml を読み込む"""
        routing_path = self._config_dir / "llm" / "routing.yaml"
        if not routing_path.exists():
            logger.warning("routing.yaml が見つかりません: %s", routing_path)
            return {}
        with routing_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _get_default_model(self) -> str:
        """routing.yaml からデフォルトモデル名を取得する"""
        # routing.yaml → default_model フィールドを参照
        default_model = self._routing.get("default_model", "")
        if not default_model:
            # フォールバック: ollama_defaults.model
            default_model = (
                self._routing.get("ollama_defaults", {}).get("model", "qwen3.5:35b-a3b")
            )
        return default_model

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        LLM を呼び出してレスポンスを返す。

        Args:
            params:
                messages (list[dict]): OpenAI 互換メッセージ配列（必須）
                model (str | None): 使用モデル（省略時は routing.yaml デフォルト）
                temperature (float | None): 温度（現在 Ollama options に渡す）
                max_tokens (int | None): 最大出力トークン数

        Returns:
            {
                "content": str,        # LLM レスポンステキスト
                "model": str,          # 使用モデル名
                "tokens_used": {
                    "prompt": int,
                    "completion": int,
                    "total": int,
                },
            }
        """
        messages: list[dict[str, str]] = params["messages"]
        model: str | None = params.get("model")
        temperature: float | None = params.get("temperature")
        max_tokens: int | None = params.get("max_tokens")

        if not messages:
            raise ValueError("messages が空です")

        # messages → prompt 変換
        prompt = _messages_to_prompt(messages)

        # Ollama options
        extra_options: dict[str, Any] = {}
        if temperature is not None:
            extra_options["temperature"] = temperature
        if max_tokens is not None:
            extra_options["num_predict"] = max_tokens

        # LLM 呼び出し
        resolved_model = model or self._get_default_model()

        response = await self._llm.generate(
            prompt=prompt,
            model=resolved_model,
            think=False,  # Phase 0 V1: think=true でタイムアウト多発 → 必須無効化
            extra_options=extra_options if extra_options else None,
        )

        tokens_used = {
            "prompt": response.prompt_eval_count,
            "completion": response.eval_count,
            "total": response.prompt_eval_count + response.eval_count,
        }

        logger.info(
            "llm_call: model=%s tokens=%d+%d=(%d) %.1f tok/s",
            response.model,
            tokens_used["prompt"],
            tokens_used["completion"],
            tokens_used["total"],
            response.tokens_per_second,
        )

        return {
            "content": response.content,
            "model": response.model,
            "tokens_used": tokens_used,
        }
