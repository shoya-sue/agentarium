"""
skills/reasoning/select_skill.py — Skill 選択 Skill

利用可能な Skill リストと現在の状態を受け取り、
LLM が次に実行すべき Skill と引数を選択する。

JSON パース失敗・タイムアウト時は IDLE にフォールバックする。

Skill 入出力スキーマ: config/skills/reasoning/select_skill.yaml
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from models.llm import LLMClient

logger = logging.getLogger(__name__)

# デフォルトモデル（高精度な意思決定のため大型モデルを使用）
_DEFAULT_MODEL: str = "qwen3.5:35b-a3b"

# フォールバック時の返却値
_IDLE_SKILL: str = "IDLE"
_FALLBACK_RESULT: dict[str, Any] = {
    "selected_skill": _IDLE_SKILL,
    "params": {},
    "reasoning": "パース失敗またはエラーによりフォールバック",
    "confidence": 0.0,
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
    """Skill 選択用のシステムプロンプトを返す。"""
    return (
        "あなたは自律型 AI Agent の意思決定コアです。\n"
        "与えられた現在の状態と利用可能なスキルのリストを分析し、\n"
        "次に実行すべき最適なスキルを 1 つ選択してください。\n\n"
        "必ず以下の JSON 形式のみで回答してください:\n"
        '{"selected_skill": "skill_name", "params": {...}, '
        '"reasoning": "理由", "confidence": 0.0〜1.0}\n\n'
        "選択肢:\n"
        "- 特にすべきことがない場合: "
        '{"selected_skill": "IDLE", "params": {}, "reasoning": "...", "confidence": 1.0}'
    )


def _build_user_prompt(
    current_state: dict[str, Any],
    available_skills: list[dict[str, Any]],
    persona_context: dict[str, Any] | None,
) -> str:
    """Skill 選択用のユーザープロンプトを構築する。"""
    parts: list[str] = []

    # ペルソナコンテキストが存在する場合は追加
    if persona_context and persona_context.get("persona_prompt"):
        parts.append(f"## キャラクター設定\n{persona_context['persona_prompt']}")

    parts.append(f"## 現在の状態\n{json.dumps(current_state, ensure_ascii=False, indent=2)}")
    parts.append(
        f"## 利用可能なスキル\n{json.dumps(available_skills, ensure_ascii=False, indent=2)}"
    )
    parts.append("最適なスキルを 1 つ選択し、JSON 形式で返してください。")

    return "\n\n".join(parts)


class SelectSkillSkill:
    """
    select_skill Skill の実装。

    利用可能な Skill リストと現在の状態から、
    LLM が次に実行すべき Skill を選択する。
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
        利用可能な Skill から次に実行すべき Skill を選択する。

        Args:
            params:
                available_skills (list[dict]): 選択肢 [{name, description, when_to_use}, ...]（必須）
                current_state (dict): WorkingMemory.to_summary_dict() の出力（必須）
                persona_context (dict | None): build_persona_context の出力
                model (str | None): 使用モデル（省略時: qwen3.5:35b-a3b）

        Returns:
            {
                "selected_skill": str,   # 選択された Skill 名（存在しない場合は IDLE）
                "params": dict,          # その Skill に渡すパラメータ
                "reasoning": str,        # 選択理由
                "confidence": float,     # 確信度 0.0〜1.0
            }
        """
        available_skills: list[dict[str, Any]] = params["available_skills"]
        current_state: dict[str, Any] = params["current_state"]
        persona_context: dict[str, Any] | None = params.get("persona_context")
        model: str = params.get("model") or _DEFAULT_MODEL

        # 利用可能な Skill 名セット（バリデーション用）
        valid_skill_names: set[str] = {s["name"] for s in available_skills} | {_IDLE_SKILL}

        # プロンプト構築
        system_prompt = _build_system_prompt()
        user_prompt = _build_user_prompt(
            current_state=current_state,
            available_skills=available_skills,
            persona_context=persona_context,
        )
        full_prompt = f"System: {system_prompt}\n\nUser: {user_prompt}"

        # LLM 呼び出し（タイムアウトや例外はフォールバック）
        try:
            response = await self._llm.generate(
                prompt=full_prompt,
                model=model,
                think=False,
            )
        except Exception as exc:
            logger.warning("select_skill: LLM 呼び出しでエラー発生: %s", exc)
            return {
                "selected_skill": _IDLE_SKILL,
                "params": {},
                "reasoning": f"LLM エラー: {type(exc).__name__}",
                "confidence": 0.0,
            }

        # JSON パース
        parsed = _parse_json_response(response.content)

        if parsed is None:
            logger.warning(
                "select_skill: JSON パース失敗、IDLE にフォールバック "
                "content='%s...'",
                response.content[:80],
            )
            return {
                "selected_skill": _IDLE_SKILL,
                "params": {},
                "reasoning": "パース失敗: LLM の出力が JSON ではありません",
                "confidence": 0.0,
            }

        # Skill 名のバリデーション（存在しない Skill は IDLE にフォールバック）
        selected_skill: str = str(parsed.get("selected_skill", _IDLE_SKILL))
        if selected_skill not in valid_skill_names:
            logger.warning(
                "select_skill: 存在しない Skill '%s' が選択されました。IDLE にフォールバック",
                selected_skill,
            )
            selected_skill = _IDLE_SKILL

        # params は dict であることを保証
        raw_params = parsed.get("params", {})
        skill_params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}

        reasoning: str = str(parsed.get("reasoning", ""))

        # confidence を 0.0〜1.0 に正規化
        raw_confidence = parsed.get("confidence", 0.0)
        try:
            confidence = float(raw_confidence)
            confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = 0.0

        logger.debug(
            "select_skill: selected=%s confidence=%.2f model=%s",
            selected_skill,
            confidence,
            model,
        )

        return {
            "selected_skill": selected_skill,
            "params": skill_params,
            "reasoning": reasoning,
            "confidence": confidence,
        }
