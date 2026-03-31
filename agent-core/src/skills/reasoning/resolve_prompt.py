"""
skills/reasoning/resolve_prompt.py — プロンプトテンプレート解決 Skill

config/prompts/{system|user|output_schema}/ 以下の YAML テンプレートを読み込み、
変数を展開して llm_call に渡す messages 配列を生成する。

Skill 入出力スキーマ: config/skills/reasoning/resolve_prompt.yaml
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# 変数プレースホルダー: {variable_name}
_VAR_PATTERN = re.compile(r"\{(\w+)\}")


class ResolvePromptSkill:
    """
    resolve_prompt Skill の実装。

    YAML テンプレートを読み込み、変数を展開して messages 配列を返す。

    テンプレート構造:
        config/prompts/system/{name}.yaml   → content フィールド（system message）
        config/prompts/user/{name}.yaml     → content フィールド（user message）
        config/prompts/output_schema/{name}.yaml → schema/example（system に自動挿入）
    """

    def __init__(self, config_dir: Path | str | None = None) -> None:
        if config_dir is None:
            # デフォルト: このファイルから5階層上の agentarium/config/
            config_dir = Path(__file__).parent.parent.parent.parent.parent / "config"
        self._config_dir = Path(config_dir)
        self._prompts_dir = self._config_dir / "prompts"

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        """YAML ファイルを読み込む"""
        if not path.exists():
            raise FileNotFoundError(f"プロンプトテンプレートが見つかりません: {path}")
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _expand_variables(self, template: str, variables: dict[str, Any]) -> str:
        """
        テンプレート文字列の {variable_name} を variables 辞書で置換する。

        未定義の変数はそのまま残す（エラーにしない）。

        Args:
            template: {var} 形式のプレースホルダーを含む文字列
            variables: 変数名 → 値の辞書

        Returns:
            変数展開済み文字列
        """
        def replacer(match: re.Match) -> str:
            key = match.group(1)
            if key in variables:
                value = variables[key]
                return str(value) if not isinstance(value, str) else value
            return match.group(0)  # 未定義変数はそのまま

        return _VAR_PATTERN.sub(replacer, template)

    def _format_output_schema(self, schema_data: dict[str, Any]) -> str:
        """
        output_schema YAML を system prompt に挿入する文字列に整形する。

        Args:
            schema_data: output_schema YAML の dict

        Returns:
            整形済み文字列（JSON スキーマ + 出力例）
        """
        parts: list[str] = ["## 出力形式（JSON）"]

        schema = schema_data.get("schema")
        if schema:
            parts.append("スキーマ:")
            parts.append("```json")
            parts.append(json.dumps(schema, ensure_ascii=False, indent=2))
            parts.append("```")

        example = schema_data.get("example")
        if example:
            parts.append("\n出力例:")
            parts.append("```json")
            # example が既に文字列なら strip、dict なら JSON 変換
            if isinstance(example, str):
                parts.append(example.strip())
            else:
                parts.append(json.dumps(example, ensure_ascii=False, indent=2))
            parts.append("```")

        return "\n".join(parts)

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        プロンプトテンプレートを読み込み、変数を展開して messages 配列を返す。

        Args:
            params:
                template_name (str): テンプレート名（必須、例: "filter_relevance"）
                variables (dict | None): 変数展開に使う辞書
                include_output_schema (bool): output_schema を system に自動挿入するか（デフォルト: True）

        Returns:
            {
                "messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}],
                "template_name": str,
                "resolved_at": str (ISO 8601),
            }
        """
        template_name: str = params["template_name"]
        variables: dict[str, Any] = params.get("variables") or {}
        include_schema: bool = bool(params.get("include_output_schema", True))

        messages: list[dict[str, str]] = []

        # --- system message ---
        system_path = self._prompts_dir / "system" / f"{template_name}.yaml"
        system_data = self._load_yaml(system_path)
        system_content: str = system_data.get("content", "")

        # output_schema を system に挿入する
        if include_schema:
            schema_path = self._prompts_dir / "output_schema" / f"{template_name}.yaml"
            if schema_path.exists():
                schema_data = self._load_yaml(schema_path)
                schema_text = self._format_output_schema(schema_data)
                variables = {**variables, "output_schema": schema_text}

        system_content = self._expand_variables(system_content, variables)
        if system_content.strip():
            messages.append({"role": "system", "content": system_content})

        # --- user message ---
        user_path = self._prompts_dir / "user" / f"{template_name}.yaml"
        user_data = self._load_yaml(user_path)
        user_content: str = user_data.get("content", "")
        user_content = self._expand_variables(user_content, variables)
        if user_content.strip():
            messages.append({"role": "user", "content": user_content})

        resolved_at = datetime.now(timezone.utc).isoformat()

        logger.debug(
            "resolve_prompt: template=%s variables=%d messages=%d",
            template_name,
            len(variables),
            len(messages),
        )

        return {
            "messages": messages,
            "template_name": template_name,
            "resolved_at": resolved_at,
        }
