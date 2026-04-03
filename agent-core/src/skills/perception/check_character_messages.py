"""
skills/perception/check_character_messages.py — キャラクター間メッセージ受信 Skill

CharacterMessageQueue から自キャラクター宛のメッセージを取り出す。
AgentLoop の check_character_messages 自動チェーンにより、
受信メッセージは WorkingMemory.pending_character_messages に格納され、
次に map_message_emotion Skill が呼び出されて感情マッピングが行われる。

Skill 入出力スキーマ: config/skills/perception/check_character_messages.yaml
"""

from __future__ import annotations

import logging
from typing import Any

from scheduler.character_message_queue import CharacterMessageQueue

logger = logging.getLogger(__name__)


class CheckCharacterMessagesSkill:
    """キャラクター間メッセージキューから受信メッセージを取り出す Skill。"""

    def __init__(self, queue: CharacterMessageQueue) -> None:
        # メッセージキューへの参照を保持する（全エージェント共有）
        self._queue = queue

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        キャラクターの受信メッセージをキューから取り出して返す。

        Parameters
        ----------
        params:
            character_name (str, 必須): 受信確認するキャラクター名（例: 'zephyr'）
            max_messages  (int, 任意): 一度に取り出す最大件数（デフォルト: 5）

        Returns
        -------
        dict:
            character_name: str
            messages: list[dict]  — CharacterMessage.to_dict() の配列
            count: int            — 取り出したメッセージ件数
            has_messages: bool    — 1件以上あれば True
            error: str            — 失敗時のみ含まれる
        """
        # 必須パラメータを取得する
        character_name: str = params["character_name"]
        max_messages: int = params.get("max_messages", 5)

        try:
            # キューからメッセージを受信する
            messages = self._queue.receive_all(character_name, max_messages)

            # 各メッセージを辞書形式に変換する
            message_dicts = [msg.to_dict() for msg in messages]

            count = len(message_dicts)
            logger.debug(
                "キャラクター '%s' の受信メッセージ: %d 件取得",
                character_name,
                count,
            )

            return {
                "character_name": character_name,
                "messages": message_dicts,
                "count": count,
                "has_messages": count > 0,
            }

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "check_character_messages 失敗 (character_name=%s): %s",
                character_name,
                exc,
            )
            return {
                "character_name": character_name,
                "messages": [],
                "count": 0,
                "has_messages": False,
                "error": str(exc),
            }
