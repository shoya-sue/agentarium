"""
models/llm.py — Ollama API ラッパー

Phase 0 V1 検証結果:
  - think=true (default): 476 tokens / 31秒 → タイムアウト多発
  - think=false: 14 tokens / 1.1秒 → 安定動作 (31.9 tok/s)

全呼び出しで think=false がデフォルト。
config/llm/routing.yaml の ollama_defaults.think=false と一致。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Ollama generate API のデフォルト設定
_DEFAULTS: dict[str, Any] = {
    "think": False,          # Phase 0 V1: think=true でタイムアウト多発 → 必須無効化
    "stream": False,
    "options": {
        "num_ctx": 16384,    # config/settings.yaml の ollama.num_ctx と一致
    },
}


@dataclass(frozen=True)
class LLMResponse:
    """Ollama API レスポンスの構造化表現"""

    model: str
    content: str               # response フィールド
    prompt_eval_count: int     # 入力トークン数
    eval_count: int            # 出力トークン数
    eval_duration_ns: int      # 出力生成時間（ナノ秒）

    @property
    def tokens_per_second(self) -> float:
        """出力トークン/秒"""
        if self.eval_duration_ns == 0:
            return 0.0
        return self.eval_count / (self.eval_duration_ns / 1e9)

    def parse_json(self) -> Any:
        """
        content を JSON としてパースする。

        JSON が埋め込まれた場合（```json...```）も対応。

        Raises:
            json.JSONDecodeError: JSON パース失敗
        """
        text = self.content.strip()

        # コードブロック除去
        if text.startswith("```"):
            lines = text.splitlines()
            # 先頭の ``` 行と末尾の ``` 行を除去
            inner = [l for l in lines[1:] if l.strip() != "```"]
            text = "\n".join(inner).strip()

        return json.loads(text)


class LLMClient:
    """
    Ollama HTTP API クライアント。

    使用例::

        client = LLMClient(base_url="http://localhost:11434", model="qwen3.5:35b-a3b")
        response = await client.generate("以下を JSON で要約してください: ...")
        data = response.parse_json()
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: int = 30,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        think: bool = False,
        extra_options: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """
        Ollama generate API を呼び出す。

        Args:
            prompt: プロンプトテキスト
            model: 使用モデル（省略時はデフォルトモデル）
            think: extended thinking モード（Phase 0 V1 により False 推奨）
            extra_options: ollama options に追加するパラメータ

        Returns:
            LLMResponse

        Raises:
            httpx.TimeoutException: タイムアウト
            httpx.HTTPStatusError: HTTP エラー
            ValueError: レスポンス構造が想定外の場合
        """
        payload: dict[str, Any] = {
            **_DEFAULTS,
            "model": model or self._model,
            "prompt": prompt,
            "think": think,
        }
        if extra_options:
            payload["options"] = {**_DEFAULTS.get("options", {}), **extra_options}

        logger.debug("LLM 呼び出し: model=%s think=%s prompt_len=%d", payload["model"], think, len(prompt))

        response = await self._client.post(
            f"{self._base_url}/api/generate",
            json=payload,
        )
        response.raise_for_status()

        data = response.json()

        # レスポンス検証
        required_keys = ("model", "response", "prompt_eval_count", "eval_count", "eval_duration")
        for key in required_keys:
            if key not in data:
                raise ValueError(f"Ollama レスポンスに '{key}' が含まれていません: {data}")

        result = LLMResponse(
            model=data["model"],
            content=data["response"],
            prompt_eval_count=data["prompt_eval_count"],
            eval_count=data["eval_count"],
            eval_duration_ns=data["eval_duration"],
        )

        logger.debug(
            "LLM 完了: %.1f tok/s (%d tokens / %.1fs)",
            result.tokens_per_second,
            result.eval_count,
            result.eval_duration_ns / 1e9,
        )

        return result

    async def close(self) -> None:
        """HTTPクライアントを閉じる"""
        await self._client.aclose()

    async def __aenter__(self) -> "LLMClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
