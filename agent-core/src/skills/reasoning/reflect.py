"""
skills/reasoning/reflect.py — 振り返り・学習 Skill

エージェントが実行した1サイクルの行動を LLM で評価し、
次サイクルへの示唆を生成する。

JSON パース失敗・タイムアウト時はフォールバック値を返す。

Skill 入出力スキーマ: config/skills/reasoning/reflect.yaml
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from models.llm import LLMClient

logger = logging.getLogger(__name__)

# デフォルトモデル（振り返りは中型モデルで十分）
_DEFAULT_MODEL: str = "qwen3.5:14b"

# スコアのクランプ範囲
_SCORE_MIN: float = 0.0
_SCORE_MAX: float = 1.0

# フォールバック時の返却値（パース失敗またはLLMエラー）
_FALLBACK_CYCLE_SUMMARY: str = "parse_failed: LLM 応答を解析できませんでした"

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


def _build_fallback_result(model: str) -> dict[str, Any]:
    """
    パース失敗またはエラー時のフォールバック結果を返す。

    Args:
        model: 使用しようとしたモデル名

    Returns:
        フォールバック値を含む dict
    """
    return {
        "cycle_summary": _FALLBACK_CYCLE_SUMMARY,
        "achievements": [],
        "failures": [],
        "key_learnings": [],
        "next_cycle_suggestions": [],
        "self_evaluation_score": 0.5,
        "model_used": model,
    }


def _build_system_prompt() -> str:
    """振り返り用のシステムプロンプトを返す。"""
    return (
        "あなたは AI エージェントの自己反省モジュールです。\n"
        "エージェントが実行したサイクルの記録を受け取り、\n"
        "客観的に評価・振り返りを行います。\n\n"
        "必ず以下の JSON 形式のみで回答してください:\n"
        "{\n"
        '  "cycle_summary": "今サイクルの活動まとめ（1-2文）",\n'
        '  "achievements": ["達成事項1", "達成事項2"],\n'
        '  "failures": ["失敗・問題点1"],\n'
        '  "key_learnings": ["学習事項1"],\n'
        '  "next_cycle_suggestions": ["次サイクルへの提案1"],\n'
        '  "self_evaluation_score": 0.75\n'
        "}\n\n"
        "self_evaluation_score は 0.0（完全失敗）〜 1.0（完璧）の実数で答えてください。"
    )


def _build_user_prompt(working_memory: dict[str, Any]) -> str:
    """
    振り返り用のユーザープロンプトを構築する。

    Args:
        working_memory: WorkingMemory.to_summary_dict() の出力

    Returns:
        ユーザープロンプト文字列
    """
    summary_json = json.dumps(working_memory, ensure_ascii=False, indent=2)
    return (
        f"## 今サイクルの実行記録\n{summary_json}\n\n"
        "上記の実行記録をもとに、このサイクルの振り返りを JSON 形式で出力してください。"
    )


def _normalize_result(
    parsed: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    """
    LLM の解析結果を正規化して返す。

    - self_evaluation_score を 0.0〜1.0 にクランプ
    - リスト型フィールドは list であることを保証
    - model_used を追加

    Args:
        parsed: LLM のパース済み dict
        model: 使用したモデル名

    Returns:
        正規化済み dict
    """
    # self_evaluation_score のクランプ
    raw_score = parsed.get("self_evaluation_score", 0.5)
    try:
        score = float(raw_score)
        score = max(_SCORE_MIN, min(_SCORE_MAX, score))
    except (TypeError, ValueError):
        score = 0.5

    # リスト型フィールドの正規化（リストでなければ空リストに変換）
    def _ensure_list(val: Any) -> list:
        return val if isinstance(val, list) else []

    return {
        "cycle_summary": str(parsed.get("cycle_summary", "")),
        "achievements": _ensure_list(parsed.get("achievements")),
        "failures": _ensure_list(parsed.get("failures")),
        "key_learnings": _ensure_list(parsed.get("key_learnings")),
        "next_cycle_suggestions": _ensure_list(parsed.get("next_cycle_suggestions")),
        "self_evaluation_score": score,
        "model_used": model,
    }


class ReflectSkill:
    """
    reflect Skill の実装。

    エージェントが実行した1サイクルの行動を LLM で評価し、
    次サイクルへの示唆と自己評価スコアを生成する。
    """

    def __init__(
        self,
        llm_client: LLMClient,
        config_dir: Path | str | None = None,
    ) -> None:
        self._llm = llm_client
        # config_dir は将来的なプロンプト YAML 読み込みに使用
        if config_dir is None:
            config_dir = Path(__file__).parent.parent.parent.parent.parent / "config"
        self._config_dir = Path(config_dir)

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        1サイクルの実行記録を振り返り、評価・学習事項を生成する。

        Args:
            params:
                working_memory (dict): WorkingMemory.to_summary_dict() の出力（必須）
                model (str | None): 使用モデル（省略時: qwen3.5:14b）

        Returns:
            {
                "cycle_summary": str,            # 今サイクルの活動まとめ
                "achievements": list[str],       # 達成事項
                "failures": list[str],           # 失敗・問題点
                "key_learnings": list[str],      # 学習事項
                "next_cycle_suggestions": list[str],  # 次サイクルへの提案
                "self_evaluation_score": float,  # 自己評価スコア 0.0〜1.0
                "model_used": str,               # 使用したモデル名
            }
        """
        working_memory: dict[str, Any] = params["working_memory"]
        model: str = params.get("model") or _DEFAULT_MODEL

        # プロンプト構築
        system_prompt = _build_system_prompt()
        user_prompt = _build_user_prompt(working_memory)
        full_prompt = f"System: {system_prompt}\n\nUser: {user_prompt}"

        # LLM 呼び出し（タイムアウトや例外はフォールバック）
        try:
            response = await self._llm.generate(
                prompt=full_prompt,
                model=model,
                think=False,
            )
        except Exception as exc:
            logger.warning("reflect: LLM 呼び出しでエラー発生: %s", exc)
            return _build_fallback_result(model)

        # JSON パース
        parsed = _parse_json_response(response.content)

        if parsed is None:
            logger.warning(
                "reflect: JSON パース失敗、フォールバック値を返す "
                "content='%s...'",
                response.content[:80],
            )
            return _build_fallback_result(model)

        # 結果を正規化して返す
        result = _normalize_result(parsed, model)

        logger.debug(
            "reflect: score=%.2f achievements=%d learnings=%d model=%s",
            result["self_evaluation_score"],
            len(result["achievements"]),
            len(result["key_learnings"]),
            model,
        )

        return result
