"""
scheduler/character_message_queue.py — キャラクター間メッセージキュー

AgentLoop の同一プロセス内で Zephyr/Lynx が非同期にメッセージを交換するための
共有インメモリキュー。asyncio.Queue ベースのシンプルな実装。

使い方:
  shared_queue = CharacterMessageQueue()
  # AgentLoop 初期化時に inject し、send_character_message / check_character_messages Skill から参照する
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CharacterMessage:
    """
    キャラクター間で交換される1メッセージ。

    Attributes:
        from_character: 送信キャラクター名（例: 'zephyr'）
        to_character: 受信キャラクター名（例: 'lynx'）
        content: メッセージ本文
        timestamp: 送信日時（ISO 8601）
        metadata: 付加情報（トピック・感情スコア等を格納可能）
    """

    from_character: str
    to_character: str
    content: str
    timestamp: str = field(default_factory=_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_character": self.from_character,
            "to_character": self.to_character,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


class CharacterMessageQueue:
    """
    キャラクター別の asyncio.Queue を管理するシングルトン的ラッパー。

    各キャラクターごとに独立したキューを保持する。
    send_character_message Skill が送信し、check_character_messages Skill が受信する。

    スレッド安全性:
        asyncio の同一イベントループ内でのみ使用することを前提とする。
        複数スレッドにまたがる場合は asyncio.Queue のスレッドセーフ API を使うこと。
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[CharacterMessage]] = {}

    def _get_queue(self, character_name: str) -> asyncio.Queue[CharacterMessage]:
        """キャラクター名に対応するキューを取得（なければ生成）。"""
        if character_name not in self._queues:
            self._queues[character_name] = asyncio.Queue()
        return self._queues[character_name]

    async def send(
        self,
        from_character: str,
        to_character: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> CharacterMessage:
        """
        メッセージを宛先キャラクターのキューに送信する。

        Args:
            from_character: 送信キャラクター名
            to_character: 受信キャラクター名
            content: メッセージ本文
            metadata: 付加情報（任意）

        Returns:
            送信した CharacterMessage
        """
        msg = CharacterMessage(
            from_character=from_character,
            to_character=to_character,
            content=content,
            metadata=metadata or {},
        )
        queue = self._get_queue(to_character)
        await queue.put(msg)
        logger.info(
            "CharacterMessageQueue: 送信完了 from=%s to=%s length=%d",
            from_character,
            to_character,
            len(content),
        )
        return msg

    def receive_all(
        self,
        character_name: str,
        max_messages: int = 5,
    ) -> list[CharacterMessage]:
        """
        キャラクターの受信キューから最大 max_messages 件を取り出す（非ブロッキング）。

        キューが空の場合は空リストを返す。

        Args:
            character_name: 受信キャラクター名
            max_messages: 1回に取り出す最大件数

        Returns:
            受信した CharacterMessage のリスト（古い順）
        """
        queue = self._get_queue(character_name)
        messages: list[CharacterMessage] = []
        while not queue.empty() and len(messages) < max_messages:
            try:
                msg = queue.get_nowait()
                messages.append(msg)
            except asyncio.QueueEmpty:
                break
        if messages:
            logger.info(
                "CharacterMessageQueue: 受信 character=%s count=%d",
                character_name,
                len(messages),
            )
        return messages

    def pending_count(self, character_name: str) -> int:
        """指定キャラクターの未処理メッセージ件数を返す。"""
        return self._get_queue(character_name).qsize()
