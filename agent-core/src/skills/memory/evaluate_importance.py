"""
skills/memory/evaluate_importance.py — コンテンツ重要度評価 Skill

LLM を使ってコンテンツの重要度を 0.0〜1.0 で判定する。
軽量判定のため qwen3.5:4b をデフォルトモデルとして使用する。

LLM 出力が不正な JSON の場合は importance_score=0.5 にフォールバック。

Skill 入出力スキーマ: config/skills/memory/evaluate_importance.yaml
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from models.llm import LLMClient

logger = logging.getLogger(__name__)

# デフォルトモデル（現在プル済みの利用可能なモデル）
# NOTE: qwen3.5:4b / qwen3.5:14b は未プル。qwen3.5:35b-a3b を使用する
_DEFAULT_MODEL: str = "qwen3.5:35b-a3b"

# パース失敗時のフォールバック値
_FALLBACK_SCORE: float = 0.5
_FALLBACK_REASONING: str = "LLM 出力のパースに失敗しました。デフォルト値を使用します。"

# 重要度スコアの保存閾値
_STORE_THRESHOLD: float = 0.4

# ```json ... ``` または ``` ... ``` ブロック抽出
_CODE_BLOCK_PATTERN = re.compile(
    r"```(?:json)?\s*([\s\S]*?)```",
    re.IGNORECASE,
)

# 最初の { ... } ブロック抽出
_OBJECT_PATTERN = re.compile(r"(\{[\s\S]*\})")


def _parse_json_response(text: str) -> dict[str, Any] | None:
    """
    LLM レスポンスから JSON をパースする。

    戦略1: テキスト全体を直接 json.loads()
    戦略2: ```json ... ``` ブロックから抽出
    戦略3: 最初の { ... } ブロックを抽出

    Returns:
        パース済み dict、失敗した場合は None
    """
    # 戦略1: 直接パース
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # 戦略2: コードブロック抽出
    match = _CODE_BLOCK_PATTERN.search(text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 戦略3: 最初のオブジェクト抽出
    match = _OBJECT_PATTERN.search(text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    return None


def _build_system_prompt() -> str:
    """重要度評価用のシステムプロンプトを返す。"""
    return (
        "You are an expert assistant that objectively evaluates the importance of content.\n"
        "Consider the informational value, relevance, and novelty of the given content, "
        "and rate it on a scale of 0.0 (not important) to 1.0 (very important).\n"
        "Respond ONLY in the following JSON format:\n"
        '{"importance_score": 0.0-1.0, "reasoning": "reason", "topics": ["topic1", ...]}'
    )


def _build_user_prompt(
    content: str,
    source: str,
    context: str | None,
) -> str:
    """重要度評価用のユーザープロンプトを構築する。"""
    parts = [
        "Evaluate the importance of the following content.",
        f"\n## Source\n{source}",
        f"\n## Content\n{content}",
    ]

    if context:
        parts.append(f"\n## Additional Context\n{context}")

    parts.append("\nReturn the importance score, reasoning, and extracted topics as JSON.")

    return "\n".join(parts)


class EvaluateImportanceSkill:
    """
    evaluate_importance Skill の実装。

    コンテンツの重要度を LLM で判定し、0.0〜1.0 のスコアを返す。
    デフォルトモデルは qwen3.5:4b（軽量判定）。
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        コンテンツの重要度を LLM で評価する。

        Args:
            params:
                content (str): 評価対象テキスト（必須）
                source (str): 情報ソース名（必須）
                context (str | None): 追加コンテキスト
                model (str | None): 使用モデル（省略時は qwen3.5:4b）

        Returns:
            {
                "importance_score": float,  # 0.0〜1.0
                "reasoning": str,           # 判定理由
                "topics": list[str],        # 抽出されたトピック
                "should_store": bool,       # importance_score >= 0.4
            }
        """
        content: str = params["content"]
        source: str = params["source"]
        context: str | None = params.get("context")
        model: str = params.get("model") or _DEFAULT_MODEL

        # プロンプト構築
        system_prompt = _build_system_prompt()
        user_prompt = _build_user_prompt(
            content=content,
            source=source,
            context=context,
        )

        # メッセージを単一プロンプトに結合（LLMClient.generate は単一プロンプトを受け取る）
        full_prompt = f"System: {system_prompt}\n\nUser: {user_prompt}"

        # LLM 呼び出し
        response = await self._llm.generate(
            prompt=full_prompt,
            model=model,
            think=False,
        )

        # JSON パース
        parsed = _parse_json_response(response.content)

        if parsed is None:
            logger.warning(
                "evaluate_importance: JSON パース失敗、フォールバック値を使用 content='%s...'",
                content[:80],
            )
            return {
                "importance_score": _FALLBACK_SCORE,
                "reasoning": _FALLBACK_REASONING,
                "topics": [],
                "should_store": _FALLBACK_SCORE >= _STORE_THRESHOLD,
            }

        # スコアの正規化（0.0〜1.0 範囲に収める）
        raw_score = parsed.get("importance_score", _FALLBACK_SCORE)
        try:
            importance_score = float(raw_score)
            importance_score = max(0.0, min(1.0, importance_score))
        except (TypeError, ValueError):
            logger.warning(
                "evaluate_importance: importance_score が数値でありません: %s",
                raw_score,
            )
            importance_score = _FALLBACK_SCORE

        reasoning: str = str(parsed.get("reasoning", _FALLBACK_REASONING))

        raw_topics = parsed.get("topics", [])
        topics: list[str] = (
            [str(t) for t in raw_topics]
            if isinstance(raw_topics, list)
            else []
        )

        should_store: bool = importance_score >= _STORE_THRESHOLD

        logger.debug(
            "evaluate_importance: source=%s score=%.2f should_store=%s topics=%s",
            source,
            importance_score,
            should_store,
            topics,
        )

        return {
            "importance_score": importance_score,
            "reasoning": reasoning,
            "topics": topics,
            "should_store": should_store,
        }
