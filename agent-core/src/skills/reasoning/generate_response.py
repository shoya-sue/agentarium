"""
skills/reasoning/generate_response.py — キャラクター応答生成 Skill

ペルソナコンテキストを使って Discord/X 向けの返答文を LLM で生成する。
LLM エラー時は response_text = "" を返す（空文字列フォールバック）。

Skill 入出力スキーマ: config/skills/reasoning/generate_response.yaml
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from models.llm import LLMClient

logger = logging.getLogger(__name__)

# デフォルトモデル（キャラクター応答は中型モデルで十分）
_DEFAULT_MODEL: str = "qwen3.5:35b-a3b"

# デフォルトプラットフォーム
_DEFAULT_PLATFORM: str = "discord"

# プラットフォーム固有の指示
_PLATFORM_INSTRUCTIONS: dict[str, str] = {
    "discord": (
        "Discord 向けの返答を生成してください。"
        "Markdown は限定的に使用し、自然な会話調で書いてください。"
        "2000文字以内に収めてください。"
    ),
    "x": (
        "X（旧Twitter）向けの返答を生成してください。"
        "140文字以内（日本語）に収めてください。"
        "ハッシュタグは必要な場合のみ使用してください。"
    ),
}


def _build_system_prompt(persona_context: dict[str, Any]) -> str:
    """
    ペルソナコンテキストから system プロンプトを組み立てる。

    Args:
        persona_context: BuildPersonaContextSkill の出力

    Returns:
        system プロンプト文字列
    """
    parts: list[str] = []

    # ペルソナプロンプト（必須）
    persona_prompt = persona_context["persona_prompt"]
    parts.append(persona_prompt)

    # スタイル指示
    style_instructions = persona_context.get("style_instructions", "")
    if style_instructions:
        parts.append(style_instructions)

    # モチベーションコンテキスト（オプション）
    motivation_context = persona_context.get("motivation_context")
    if motivation_context:
        parts.append(motivation_context)

    return "\n\n".join(parts)


def _build_user_prompt(trigger: str, platform: str) -> str:
    """
    user プロンプトを組み立てる。

    Args:
        trigger: 返答のトリガーとなったイベント/メッセージ
        platform: 出力プラットフォーム ("discord" | "x")

    Returns:
        user プロンプト文字列
    """
    platform_instruction = _PLATFORM_INSTRUCTIONS.get(
        platform,
        "返答を生成してください。",
    )

    return (
        f"## トリガー\n{trigger}\n\n"
        f"## 指示\n{platform_instruction}\n\n"
        "上記トリガーに対して、キャラクターとして自然な返答を生成してください。"
        "返答本文のみを出力してください（前置きや説明は不要です）。"
    )


class GenerateResponseSkill:
    """
    generate_response Skill の実装。

    キャラクターとして Discord/X 向けの返答文を LLM で生成する。
    LLM エラー時は response_text = "" のフォールバックを返す。
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
        キャラクターとして返答文を生成する。

        Args:
            params:
                persona_context (dict): BuildPersonaContextSkill の出力（必須）
                    - persona_prompt (str): ペルソナ記述（必須）
                    - style_instructions (str): スタイル指示
                    - motivation_context (str | None): モチベーションコンテキスト
                    - character_name (str): キャラクター名
                trigger (str): 返答のトリガーとなったイベント/メッセージ（必須）
                context_messages (list[dict] | None): 追加文脈（OpenAI messages 形式）
                platform (str | None): "discord" or "x"（デフォルト: "discord"）
                model (str | None): LLMモデル名（デフォルト: qwen3.5:14b）

        Returns:
            {
                "response_text": str,    # 生成されたレスポンス本文（エラー時は空文字列）
                "character_name": str,   # ペルソナ名
                "platform": str,         # 使用プラットフォーム
                "model_used": str,       # 使用したモデル名
                "token_estimate": int,   # response_text の文字数 / 4
            }

        Raises:
            ValueError: persona_context に persona_prompt キーがない場合
        """
        persona_context: dict[str, Any] = params["persona_context"]
        trigger: str = params["trigger"]
        platform: str = params.get("platform") or _DEFAULT_PLATFORM
        model: str = params.get("model") or _DEFAULT_MODEL
        # context_messages は将来の拡張用（現在は未使用）
        _context_messages: list[dict[str, Any]] | None = params.get("context_messages")

        # persona_prompt の存在チェック（必須フィールド）
        if "persona_prompt" not in persona_context:
            raise ValueError(
                "persona_context に 'persona_prompt' キーが必要です。"
                "BuildPersonaContextSkill の出力を渡してください。"
            )

        # キャラクター名の取得
        character_name: str = persona_context.get("character_name", "unknown")

        # プロンプト構築
        system_prompt = _build_system_prompt(persona_context)
        user_prompt = _build_user_prompt(trigger=trigger, platform=platform)
        full_prompt = f"System: {system_prompt}\n\nUser: {user_prompt}"

        # LLM 呼び出し（エラー時は空文字列フォールバック）
        response_text: str = ""
        try:
            response = await self._llm.generate(
                prompt=full_prompt,
                model=model,
                think=False,
            )
            response_text = response.content
        except Exception as exc:
            logger.warning(
                "generate_response: LLM 呼び出しでエラー発生: %s",
                exc,
            )
            # エラー時は空文字列でフォールバック

        # トークン推定（文字数 / 4）
        token_estimate: int = len(response_text) // 4

        logger.debug(
            "generate_response: character=%s platform=%s model=%s tokens=%d",
            character_name,
            platform,
            model,
            token_estimate,
        )

        return {
            "response_text": response_text,
            "character_name": character_name,
            "platform": platform,
            "model_used": model,
            "token_estimate": token_estimate,
        }
