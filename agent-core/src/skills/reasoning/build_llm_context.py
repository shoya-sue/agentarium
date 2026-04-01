"""
skills/reasoning/build_llm_context.py — LLM コンテキスト組み立て Skill

WorkingMemory サマリ・想起済み記憶・ペルソナコンテキストを
LLM に渡す messages 配列に組み立てる。

LLM を呼び出さない（テンプレート組み立てのみ）。
Skill 入出力スキーマ: config/skills/reasoning/build_llm_context.yaml
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# トークン推定の除数（文字数 / 4 でおおよそのトークン数を推定）
_CHARS_PER_TOKEN: int = 4

# context_limits.yaml が見つからない場合のデフォルトトークン上限
_DEFAULT_MAX_TOKENS: int = 8000

# セクションの優先度順（数値が小さいほど高優先度）
_DEFAULT_SECTION_PRIORITIES: dict[str, int] = {
    "system_prompt": 1,
    "current_state": 2,
    "recalled_memories": 3,
    "available_skills": 4,
    "persona": 5,
    "extra": 6,
}


def _estimate_tokens(text: str) -> int:
    """文字数を 4 で割ってトークン数を推定する。"""
    return max(1, len(text) // _CHARS_PER_TOKEN)


class BuildLlmContextSkill:
    """
    build_llm_context Skill の実装。

    WorkingMemory のサマリ・recalled_memories・ペルソナコンテキストを
    LLM messages 配列に変換する。LLM は呼び出さない。
    """

    def __init__(
        self,
        config_dir: Path | str | None = None,
    ) -> None:
        if config_dir is None:
            # デフォルト: agentarium/config
            config_dir = Path(__file__).parent.parent.parent.parent.parent / "config"
        self._config_dir = Path(config_dir)
        self._context_limits = self._load_context_limits()

    def _load_context_limits(self) -> dict[str, Any]:
        """config/llm/context_limits.yaml を読み込む。"""
        limits_path = self._config_dir / "llm" / "context_limits.yaml"
        if not limits_path.exists():
            logger.warning("context_limits.yaml が見つかりません: %s", limits_path)
            return {}
        with limits_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _get_max_tokens(self, model: str | None) -> int:
        """モデルに応じたトークン上限を返す。"""
        if not model:
            return _DEFAULT_MAX_TOKENS
        limits = self._context_limits.get("context_limits", {})
        model_config = limits.get(model, {})
        return model_config.get("available_for_input", _DEFAULT_MAX_TOKENS)

    def _get_section_priorities(self, model: str | None) -> dict[str, int]:
        """モデルに応じたセクション優先度辞書を返す。"""
        if not model:
            return _DEFAULT_SECTION_PRIORITIES
        limits = self._context_limits.get("context_limits", {})
        model_config = limits.get(model, {})
        sections = model_config.get("sections", {})
        if not sections:
            return _DEFAULT_SECTION_PRIORITIES
        # YAML の sections → {name: priority} に変換
        return {name: cfg.get("priority", 99) for name, cfg in sections.items()}

    def _build_system_content(
        self,
        working_memory: dict[str, Any],
        persona_context: dict[str, Any] | None,
    ) -> tuple[str, list[str]]:
        """
        system メッセージの本文と使用したセクション名リストを返す。

        Returns:
            (content, sections_used)
        """
        parts: list[str] = []
        sections_used: list[str] = []

        # ペルソナプロンプト
        if persona_context and persona_context.get("persona_prompt"):
            parts.append(persona_context["persona_prompt"])
            sections_used.append("persona")

        # 現在の状態サマリ
        current_goal = working_memory.get("current_goal", "なし")
        cycle_count = working_memory.get("cycle_count", 0)
        active_character = working_memory.get("active_character", "unknown")

        state_lines = [
            "## 現在の状態",
            f"- 目標: {current_goal}",
            f"- サイクル数: {cycle_count}",
            f"- アクティブキャラクター: {active_character}",
        ]

        # プラン情報（未完了ステップのみ）
        plan_steps = working_memory.get("plan_steps", [])
        pending = [s for s in plan_steps if not s.get("done", False)]
        if pending:
            state_lines.append("- 未完了ステップ: " + ", ".join(s["skill"] for s in pending))

        parts.append("\n".join(state_lines))
        sections_used.append("current_state")

        # 利用可能な Skill リスト
        available_skills = working_memory.get("available_skills", [])
        if available_skills:
            skills_text = "## 利用可能な Skill\n" + "\n".join(
                f"- {skill}" for skill in available_skills
            )
            parts.append(skills_text)
            sections_used.append("available_skills")

        return "\n\n".join(parts), sections_used

    def _build_user_content(
        self,
        target_skill: str,
        recalled_memories: list[dict[str, Any]],
    ) -> tuple[str, list[str]]:
        """
        user メッセージの本文と使用したセクション名リストを返す。

        recalled_memories はスコア降順でソートして含める。

        Returns:
            (content, sections_used)
        """
        parts: list[str] = []
        sections_used: list[str] = []

        # タスク記述
        parts.append(f"## タスク: {target_skill} を実行してください")
        sections_used.append("task")

        # 想起した記憶（スコア降順）
        if recalled_memories:
            sorted_memories = sorted(
                recalled_memories,
                key=lambda m: m.get("score", 0.0),
                reverse=True,
            )
            memory_lines = ["## 関連する記憶"]
            for mem in sorted_memories:
                content = mem.get("content", "")
                score = mem.get("score", 0.0)
                if content:
                    memory_lines.append(f"- [{score:.2f}] {content}")
            parts.append("\n".join(memory_lines))
            sections_used.append("recalled_memories")

        return "\n\n".join(parts), sections_used

    def _truncate_to_limit(
        self,
        system_content: str,
        user_content: str,
        max_tokens: int,
        section_priorities: dict[str, int],
    ) -> tuple[str, str, list[str]]:
        """
        トークン上限を超えている場合に低優先度セクションを削減する。

        Returns:
            (system_content, user_content, truncated_sections)
        """
        truncated: list[str] = []
        current_tokens = _estimate_tokens(system_content + user_content)

        if current_tokens <= max_tokens:
            return system_content, user_content, truncated

        # 削減対象: recalled_memories セクション（user_content から削減）
        if "## 関連する記憶" in user_content:
            # 記憶セクションを除去
            lines = user_content.split("\n\n")
            filtered = [line for line in lines if "## 関連する記憶" not in line]
            user_content = "\n\n".join(filtered)
            truncated.append("recalled_memories")

            current_tokens = _estimate_tokens(system_content + user_content)
            if current_tokens <= max_tokens:
                return system_content, user_content, truncated

        # さらに available_skills を削減
        if "## 利用可能な Skill" in system_content:
            lines = system_content.split("\n\n")
            filtered = [line for line in lines if "## 利用可能な Skill" not in line]
            system_content = "\n\n".join(filtered)
            truncated.append("available_skills")

        return system_content, user_content, truncated

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        LLM messages 配列を組み立てて返す。

        Args:
            params:
                target_skill (str): コンテキストを構築する対象 Skill 名（必須）
                working_memory (dict): WorkingMemory.to_summary_dict() の出力（必須）
                recalled_memories (list[dict] | None): recall_related の結果
                persona_context (dict | None): build_persona_context の出力
                max_tokens (int | None): トークン上限
                model (str | None): 対象モデル名

        Returns:
            {
                "messages": list[dict],
                "token_estimate": int,
                "sections_used": list[str],
                "truncated_sections": list[str],
            }
        """
        target_skill: str = params["target_skill"]
        working_memory: dict[str, Any] = params["working_memory"]
        recalled_memories: list[dict[str, Any]] = params.get("recalled_memories") or []
        persona_context: dict[str, Any] | None = params.get("persona_context")
        model: str | None = params.get("model")

        # トークン上限を決定
        max_tokens: int
        if params.get("max_tokens") is not None:
            max_tokens = int(params["max_tokens"])
        else:
            max_tokens = self._get_max_tokens(model)

        section_priorities = self._get_section_priorities(model)

        # system / user メッセージを組み立てる
        system_content, system_sections = self._build_system_content(
            working_memory=working_memory,
            persona_context=persona_context,
        )
        user_content, user_sections = self._build_user_content(
            target_skill=target_skill,
            recalled_memories=recalled_memories,
        )

        # トークン削減処理
        system_content, user_content, truncated_sections = self._truncate_to_limit(
            system_content=system_content,
            user_content=user_content,
            max_tokens=max_tokens,
            section_priorities=section_priorities,
        )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

        # 全体のセクション使用リスト（削減されたものは除外）
        all_sections = system_sections + user_sections
        sections_used = [s for s in all_sections if s not in truncated_sections]

        token_estimate = _estimate_tokens(system_content + user_content)

        logger.debug(
            "build_llm_context: target_skill=%s tokens=%d sections=%s truncated=%s",
            target_skill,
            token_estimate,
            sections_used,
            truncated_sections,
        )

        return {
            "messages": messages,
            "token_estimate": token_estimate,
            "sections_used": sections_used,
            "truncated_sections": truncated_sections,
        }
