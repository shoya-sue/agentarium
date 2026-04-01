"""
skills/reasoning/generate_goal.py — 自律目標生成 Skill

現在の状態・キャラクター設定・最近の記憶をもとに、
LLM が次に達成すべき目標を自律的に生成する。

JSON パース失敗・タイムアウト時はフォールバック目標にフォールバックする。

Skill 入出力スキーマ: config/skills/reasoning/generate_goal.yaml
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from models.llm import LLMClient

logger = logging.getLogger(__name__)

# デフォルトモデル（目標生成は高精度が必要）
_DEFAULT_MODEL: str = "qwen3.5:35b-a3b"

# 有効な goal_type 一覧
VALID_GOAL_TYPES: frozenset[str] = frozenset({
    "information_collection",  # 情報収集
    "reflection",              # 振り返り・学習
    "discord_response",        # Discord 応答生成
    "memory_maintenance",      # 記憶圧縮・整理
    "idle",                    # 特にすることがない
})

# フォールバック目標テキスト
FALLBACK_GOAL: str = "新しい情報を収集する"

# フォールバック結果
_FALLBACK_RESULT: dict[str, Any] = {
    "goal": FALLBACK_GOAL,
    "goal_type": "information_collection",
    "priority": 0.0,
    "reasoning": "フォールバック: LLM エラーまたはパース失敗",
}

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
    """目標生成用のシステムプロンプトを返す。"""
    goal_types_str = " | ".join(sorted(VALID_GOAL_TYPES))
    return (
        "あなたは自律型 AI Agent の目標設定コアです。\n"
        "現在の状態・キャラクター設定・最近の記憶を分析し、\n"
        "次に Agent が取り組むべき最適な目標を 1 つ生成してください。\n\n"
        "必ず以下の JSON 形式のみで回答してください:\n"
        '{"goal": "具体的な目標の説明", '
        f'"goal_type": "{goal_types_str} のいずれか", '
        '"priority": 0.0〜1.0, '
        '"reasoning": "この目標を選んだ理由"}\n\n'
        "判断基準:\n"
        "- 長時間同じ行動を繰り返している場合は reflection を選ぶ\n"
        "- Discord への応答が溜まっている場合は discord_response を優先する\n"
        "- 記憶が肥大化している場合は memory_maintenance を選ぶ\n"
        "- 上記に当てはまらない場合は information_collection を選ぶ"
    )


def _build_user_prompt(
    current_state: dict[str, Any],
    persona_context: dict[str, Any] | None,
    recent_memories: list[dict[str, Any]] | None,
) -> str:
    """目標生成用のユーザープロンプトを構築する。"""
    parts: list[str] = []

    # ペルソナコンテキストが存在する場合は追加
    if persona_context and persona_context.get("persona_prompt"):
        parts.append(f"## キャラクター設定\n{persona_context['persona_prompt']}")

    parts.append(
        f"## 現在の状態\n{json.dumps(current_state, ensure_ascii=False, indent=2)}"
    )

    if recent_memories:
        memories_text = json.dumps(recent_memories, ensure_ascii=False, indent=2)
        parts.append(f"## 最近の記憶\n{memories_text}")

    parts.append("次に取り組むべき目標を JSON 形式で生成してください。")

    return "\n\n".join(parts)


def _normalize_priority(raw: Any) -> float:
    """priority を 0.0〜1.0 の float に正規化する。"""
    try:
        value = float(raw)
        return max(0.0, min(1.0, value))
    except (TypeError, ValueError):
        return 0.0


class GenerateGoalSkill:
    """
    generate_goal Skill の実装。

    現在の状態・キャラクター設定・最近の記憶から、
    LLM が次に達成すべき目標を自律的に生成する。
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

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        次に達成すべき目標を LLM で生成する。

        Args:
            params:
                current_state (dict): WorkingMemory.to_summary_dict() の出力（必須）
                persona_context (dict | None): build_persona_context の出力
                recent_memories (list[dict] | None): 最近の記憶リスト
                model (str | None): 使用モデル（省略時: qwen3.5:35b-a3b）

        Returns:
            {
                "goal": str,        # 生成された目標テキスト
                "goal_type": str,   # 目標の種類（VALID_GOAL_TYPES のいずれか）
                "priority": float,  # 優先度 0.0〜1.0
                "reasoning": str,   # 目標を選んだ理由
            }
        """
        current_state: dict[str, Any] = params["current_state"]
        persona_context: dict[str, Any] | None = params.get("persona_context")
        recent_memories: list[dict[str, Any]] | None = params.get("recent_memories")
        model: str = params.get("model") or _DEFAULT_MODEL

        # プロンプト構築
        system_prompt = _build_system_prompt()
        user_prompt = _build_user_prompt(
            current_state=current_state,
            persona_context=persona_context,
            recent_memories=recent_memories,
        )
        full_prompt = f"System: {system_prompt}\n\nUser: {user_prompt}"

        # LLM 呼び出し
        try:
            response = await self._llm.generate(
                prompt=full_prompt,
                model=model,
                think=False,
            )
        except Exception as exc:
            logger.warning("generate_goal: LLM 呼び出しでエラー発生: %s", exc)
            return {
                "goal": FALLBACK_GOAL,
                "goal_type": "information_collection",
                "priority": 0.0,
                "reasoning": f"LLM エラー: {type(exc).__name__}",
            }

        # JSON パース
        parsed = _parse_json_response(response.content)

        if parsed is None:
            logger.warning(
                "generate_goal: JSON パース失敗、フォールバック "
                "content='%s...'",
                response.content[:80],
            )
            return {
                "goal": FALLBACK_GOAL,
                "goal_type": "information_collection",
                "priority": 0.0,
                "reasoning": "パース失敗: LLM の出力が JSON ではありません",
            }

        # goal を文字列に変換
        goal = str(parsed.get("goal") or FALLBACK_GOAL)

        # goal_type のバリデーション（未知の値は information_collection にフォールバック）
        raw_goal_type = str(parsed.get("goal_type", "information_collection"))
        goal_type = raw_goal_type if raw_goal_type in VALID_GOAL_TYPES else "information_collection"
        if raw_goal_type not in VALID_GOAL_TYPES:
            logger.warning(
                "generate_goal: 未知の goal_type '%s' → information_collection にフォールバック",
                raw_goal_type,
            )

        # priority を正規化
        priority = _normalize_priority(parsed.get("priority", 0.5))

        # reasoning を文字列に変換
        reasoning = str(parsed.get("reasoning", ""))

        logger.debug(
            "generate_goal: goal_type=%s priority=%.2f model=%s goal='%s...'",
            goal_type,
            priority,
            model,
            goal[:50],
        )

        return {
            "goal": goal,
            "goal_type": goal_type,
            "priority": priority,
            "reasoning": reasoning,
        }
