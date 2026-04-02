"""
skills/reasoning/plan_task.py — タスク計画立案 Skill

目標と利用可能な Skill から、複数ステップの実行計画を LLM で生成する。

JSON パース失敗・タイムアウト時は空の計画にフォールバックする。
available_skills に存在しない Skill が含まれる場合はその step を除外する。

Skill 入出力スキーマ: config/skills/reasoning/plan_task.yaml
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from models.llm import LLMClient

logger = logging.getLogger(__name__)

# デフォルトモデル（高精度な計画立案のため大型モデルを使用）
_DEFAULT_MODEL: str = "gemma3:27b"

# デフォルト最大ステップ数
_DEFAULT_MAX_STEPS: int = 5

# フォールバック時の返却値
_FALLBACK_RESULT: dict[str, Any] = {
    "steps": [],
    "estimated_duration_sec": 0,
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


def _build_system_prompt(max_steps: int) -> str:
    """計画立案用のシステムプロンプトを返す。"""
    return (
        "あなたは AI Agent の実行計画を立案するプランナーです。\n"
        "指定された目標を達成するための、具体的な実行ステップを生成してください。\n\n"
        "必ず以下の JSON 形式のみで回答してください:\n"
        "{\n"
        '  "steps": [\n'
        '    {"skill": "skill_name", "params": {...}, '
        '"expected_outcome": "期待する結果", "order": 0},\n'
        "    ...\n"
        "  ],\n"
        '  "estimated_duration_sec": 60\n'
        "}\n\n"
        "制約:\n"
        f"- 最大 {max_steps} ステップ以内に収めること\n"
        "- 利用可能なスキルのみ使用すること\n"
        "- ステップは依存関係を考慮した順序にすること"
    )


def _build_user_prompt(
    goal: str,
    available_skills: list[dict[str, Any]],
    context: dict[str, Any] | None,
) -> str:
    """計画立案用のユーザープロンプトを構築する。"""
    parts: list[str] = [
        f"## 目標\n{goal}",
        f"## 利用可能なスキル\n{json.dumps(available_skills, ensure_ascii=False, indent=2)}",
    ]

    if context:
        parts.append(
            f"## 追加コンテキスト\n{json.dumps(context, ensure_ascii=False, indent=2)}"
        )

    parts.append("上記の目標を達成するための実行計画を JSON 形式で返してください。")

    return "\n\n".join(parts)


def _filter_valid_steps(
    steps: list[Any],
    valid_skill_names: set[str],
) -> list[dict[str, Any]]:
    """
    steps リストから valid_skill_names に存在する Skill のみを抽出する。

    Args:
        steps: LLM が生成したステップリスト
        valid_skill_names: 有効な Skill 名セット

    Returns:
        バリデーション済みのステップリスト
    """
    filtered: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        skill_name = step.get("skill", "")
        if skill_name not in valid_skill_names:
            logger.warning(
                "plan_task: 存在しない Skill '%s' をステップから除外しました",
                skill_name,
            )
            continue
        filtered.append({
            "skill": str(skill_name),
            "params": step.get("params", {}) if isinstance(step.get("params"), dict) else {},
            "expected_outcome": str(step.get("expected_outcome", "")),
            "order": int(step.get("order", len(filtered))),
        })
    return filtered


class PlanTaskSkill:
    """
    plan_task Skill の実装。

    目標と利用可能な Skill から複数ステップの実行計画を LLM で生成する。
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
        目標を達成するための実行計画を LLM で生成する。

        Args:
            params:
                goal (str): 達成すべき目標の記述（必須）
                available_skills (list[dict]): 利用可能な Skill リスト（必須）
                context (dict | None): 追加コンテキスト（直前の実行結果など）
                max_steps (int): 最大ステップ数（デフォルト: 5）
                model (str | None): 使用モデル（省略時: qwen3.5:35b-a3b）

        Returns:
            {
                "steps": list[dict],           # [{skill, params, expected_outcome, order}, ...]
                "estimated_duration_sec": int,  # 推定所要時間（秒）
            }
        """
        goal: str = params["goal"]
        available_skills: list[dict[str, Any]] = params["available_skills"]
        context: dict[str, Any] | None = params.get("context")
        max_steps: int = int(params.get("max_steps") or _DEFAULT_MAX_STEPS)
        model: str = params.get("model") or _DEFAULT_MODEL

        # 利用可能な Skill 名セット（バリデーション用）
        valid_skill_names: set[str] = {s["name"] for s in available_skills}

        # プロンプト構築
        system_prompt = _build_system_prompt(max_steps=max_steps)
        user_prompt = _build_user_prompt(
            goal=goal,
            available_skills=available_skills,
            context=context,
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
            logger.warning("plan_task: LLM 呼び出しでエラー発生: %s", exc)
            return {"steps": [], "estimated_duration_sec": 0}

        # JSON パース
        parsed = _parse_json_response(response.content)

        if parsed is None:
            logger.warning(
                "plan_task: JSON パース失敗、空の計画にフォールバック "
                "content='%s...'",
                response.content[:80],
            )
            return {"steps": [], "estimated_duration_sec": 0}

        # ステップのバリデーション（存在しない Skill を除外）
        raw_steps = parsed.get("steps", [])
        steps = _filter_valid_steps(
            steps=raw_steps if isinstance(raw_steps, list) else [],
            valid_skill_names=valid_skill_names,
        )

        # estimated_duration_sec を整数に変換
        raw_duration = parsed.get("estimated_duration_sec", 0)
        try:
            estimated_duration_sec = int(raw_duration)
        except (TypeError, ValueError):
            estimated_duration_sec = 0

        logger.debug(
            "plan_task: goal='%s' steps=%d duration=%ds model=%s",
            goal[:50],
            len(steps),
            estimated_duration_sec,
            model,
        )

        return {
            "steps": steps,
            "estimated_duration_sec": estimated_duration_sec,
        }
