"""
skills/action/send_character_message.py — キャラクター間メッセージ送信 Skill

キャラクター（Zephyr/Lynx）間でメッセージを送信し、同時に Discord にも投稿する。
メッセージは CharacterMessageQueue に格納され、受信側 AgentLoop の
check_character_messages Skill で取り出される。

Skill 入出力スキーマ: config/skills/action/send_character_message.yaml
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from scheduler.character_message_queue import CharacterMessageQueue
from skills.action.send_discord import SendDiscordSkill

logger = logging.getLogger(__name__)

# キャラクター表示名マッピング（小文字キー → Discord 表示用名前）
_DISPLAY_NAMES: dict[str, str] = {
    "zephyr": "Zephyr",
    "lynx": "Lynx",
}


def _get_display_name(character_name: str) -> str:
    """
    キャラクター名から表示名を返す。
    未登録の場合はそのまま返す（大文字化して返す）。
    """
    return _DISPLAY_NAMES.get(character_name.lower(), character_name.capitalize())


def _format_discord_message(from_character: str, to_character: str, content: str) -> str:
    """
    Discord 投稿用メッセージをフォーマットする。
    例: **Zephyr → Lynx**: こんにちは
    """
    from_display = _get_display_name(from_character)
    to_display = _get_display_name(to_character)
    return f"**{from_display} → {to_display}**: {content}"


class SendCharacterMessageSkill:
    """
    send_character_message Skill の実装。

    キャラクター間メッセージを CharacterMessageQueue に格納し、
    同時に Discord Webhook にも投稿する。

    Discord 送信の失敗はログ警告のみとし、キュー送信が成功していれば
    全体として成功扱いとする（Discord は通知チャネルであり必須ではない）。
    """

    def __init__(
        self,
        queue: CharacterMessageQueue,
        config_dir: Path | str | None = None,
    ) -> None:
        """
        Args:
            queue: キャラクター間メッセージキュー（AgentLoop からインジェクト）
            config_dir: config ディレクトリのパス（None の場合は自動解決）
        """
        self._queue = queue
        # config_dir を Path に統一する（SendDiscordSkill と同じ解決ロジックを使用）
        self._config_dir: Path | None = Path(config_dir) if config_dir is not None else None

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        キャラクター間メッセージを送信する。

        Args:
            params:
                from_character (str): 送信キャラクター名（例: 'zephyr'）
                to_character   (str): 受信キャラクター名（例: 'lynx'）
                content        (str): メッセージ本文
                metadata       (dict | None): 付加情報（トピック・感情コンテキスト等）

        Returns:
            {
                "sent": bool,
                "from_character": str,
                "to_character": str,
                "content_length": int,
                "queued": bool,
                "discord_sent": bool,
                "timestamp": str,   # ISO 8601
                "error": str,       # sent=False の場合のみ
            }
        """
        # --- 入力バリデーション ---
        from_character: str | None = params.get("from_character")
        to_character: str | None = params.get("to_character")
        content: str | None = params.get("content")
        metadata: dict[str, Any] | None = params.get("metadata")

        # 必須パラメータの存在確認
        missing = [k for k, v in [
            ("from_character", from_character),
            ("to_character", to_character),
            ("content", content),
        ] if not v]
        if missing:
            raise ValueError(
                f"必須パラメータが不足しています: {', '.join(missing)}"
            )

        # 型チェック（mypy 的にここで確定させる）
        assert isinstance(from_character, str)
        assert isinstance(to_character, str)
        assert isinstance(content, str)

        # --- CharacterMessageQueue への送信 ---
        try:
            msg = await self._queue.send(
                from_character=from_character,
                to_character=to_character,
                content=content,
                metadata=metadata,
            )
        except Exception as exc:
            logger.error(
                "send_character_message: キュー送信エラー from=%s to=%s error=%s",
                from_character,
                to_character,
                exc,
            )
            return {
                "sent": False,
                "error": str(exc),
            }

        # --- Discord への通知送信 ---
        discord_sent = await self._send_to_discord(
            from_character=from_character,
            to_character=to_character,
            content=content,
        )

        # --- 戻り値（immutable dict として構築、フィールドを逐次マージしない）---
        return {
            "sent": True,
            "from_character": from_character,
            "to_character": to_character,
            "content_length": len(content),
            "queued": True,
            "discord_sent": discord_sent,
            "timestamp": msg.timestamp,
        }

    async def _send_to_discord(
        self,
        from_character: str,
        to_character: str,
        content: str,
    ) -> bool:
        """
        Discord Webhook にキャラクター間メッセージを投稿する。

        Discord 送信は補助的な通知チャネルであるため、失敗しても例外を送出せず
        False を返す。

        Args:
            from_character: 送信キャラクター名
            to_character: 受信キャラクター名
            content: メッセージ本文

        Returns:
            Discord 送信成否
        """
        try:
            # SendDiscordSkill のインスタンスを生成（config_dir を引き継ぐ）
            discord_skill = SendDiscordSkill(config_dir=self._config_dir)

            # character_name を渡してキャラクター別 Webhook URL を選択させる
            # username は Discord Webhook 側で設定済みのため不要
            result = await discord_skill.run({
                "message": content,
                "character_name": from_character,
            })

            if result.get("sent"):
                logger.debug(
                    "send_character_message: Discord 送信成功 from=%s to=%s",
                    from_character,
                    to_character,
                )
                return True

            logger.warning(
                "send_character_message: Discord 送信失敗（スキップ）from=%s to=%s result=%s",
                from_character,
                to_character,
                result,
            )
            return False

        except Exception as exc:
            logger.warning(
                "send_character_message: Discord 送信エラー（スキップ）from=%s to=%s error=%s",
                from_character,
                to_character,
                exc,
            )
            return False
