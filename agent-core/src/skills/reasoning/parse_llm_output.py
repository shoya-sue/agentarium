"""
skills/reasoning/parse_llm_output.py — LLM 出力 JSON パース Skill

LLM の生テキストから JSON を抽出する。3 段階の戦略でフォールバック。
Phase 2 で retry_with_llm を有効化予定（現在は False）。

Skill 入出力スキーマ: config/skills/reasoning/parse_llm_output.yaml
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ```json ... ``` または ``` ... ``` ブロック抽出
_CODE_BLOCK_PATTERN = re.compile(
    r"```(?:json)?\s*([\s\S]*?)```",
    re.IGNORECASE,
)

# 最初の { ... } または [ ... ] ブロック抽出（最短マッチ非推奨 → グリーディで末尾 } を探す）
_OBJECT_PATTERN = re.compile(r"(\{[\s\S]*\}|\[[\s\S]*\])")


def _try_direct_json(text: str) -> tuple[Any, bool]:
    """戦略 1: テキストをそのまま json.loads()"""
    try:
        return json.loads(text.strip()), True
    except json.JSONDecodeError:
        return None, False


def _try_code_block(text: str) -> tuple[Any, bool]:
    """戦略 2: ```json ... ``` コードブロックから抽出"""
    match = _CODE_BLOCK_PATTERN.search(text)
    if not match:
        return None, False
    inner = match.group(1).strip()
    try:
        return json.loads(inner), True
    except json.JSONDecodeError:
        return None, False


def _try_first_object(text: str) -> tuple[Any, bool]:
    """戦略 3: テキスト内の最初の { ... } または [ ... ] を抽出"""
    match = _OBJECT_PATTERN.search(text)
    if not match:
        return None, False
    candidate = match.group(1).strip()
    try:
        return json.loads(candidate), True
    except json.JSONDecodeError:
        return None, False


class ParseLlmOutputSkill:
    """
    parse_llm_output Skill の実装。

    LLM レスポンス（生テキスト）から JSON を 3 戦略でフォールバック抽出する。
      1. direct_json      — テキスト全体を json.loads()
      2. extract_code_block — ```json...``` ブロックから抽出
      3. extract_first_object — 最初の { } または [ ] を抽出
    """

    _STRATEGIES = [
        ("direct_json", _try_direct_json),
        ("extract_code_block", _try_code_block),
        ("extract_first_object", _try_first_object),
    ]

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        LLM 生テキストから JSON を抽出・パースする。

        Args:
            params:
                raw_text (str): llm_call の output.content（必須）
                expected_schema (dict | None): 期待する JSON スキーマ（バリデーション用、現在は参考情報のみ）
                fallback_value (Any): パース失敗時のデフォルト値（None の場合は ValueError を raise）

        Returns:
            {
                "parsed": Any,          # パース済みオブジェクト
                "success": bool,
                "strategy_used": str,   # 使用した戦略名
                "error": str | None,    # 失敗時のエラーメッセージ
                "raw_json": str | None, # 抽出された JSON 文字列（デバッグ用）
            }
        """
        raw_text: str = params["raw_text"]
        fallback_value = params.get("fallback_value", _SENTINEL)

        errors: list[str] = []
        strategy_used: str = ""
        parsed: Any = None

        for strategy_name, strategy_fn in self._STRATEGIES:
            result, ok = strategy_fn(raw_text)
            if ok:
                parsed = result
                strategy_used = strategy_name
                logger.debug(
                    "parse_llm_output: 戦略 '%s' で JSON 抽出成功",
                    strategy_name,
                )
                return {
                    "parsed": parsed,
                    "success": True,
                    "strategy_used": strategy_used,
                    "error": None,
                    "raw_json": json.dumps(parsed, ensure_ascii=False),
                }
            else:
                errors.append(f"{strategy_name}: パース失敗")

        # 全戦略失敗
        error_msg = "; ".join(errors)
        logger.warning(
            "parse_llm_output: 全戦略失敗 raw_text='%s...' errors=%s",
            raw_text[:80],
            error_msg,
        )

        if fallback_value is _SENTINEL:
            raise ValueError(
                f"LLM 出力の JSON 抽出に失敗しました。raw_text='{raw_text[:100]}...'\n{error_msg}"
            )

        return {
            "parsed": fallback_value,
            "success": False,
            "strategy_used": "fallback",
            "error": error_msg,
            "raw_json": None,
        }


# fallback_value が指定されていない場合のセンチネル値
_SENTINEL = object()
