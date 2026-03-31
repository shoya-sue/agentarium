"""
adapters/base.py — ソースアダプタ基底クラスと共通データ型

アダプタパターン: 情報源は Skill ではなく YAML 設定で追加。
共通基盤 + ソースアダプタ（CLAUDE.md 設計原則）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class FetchedItem:
    """アダプタが返す統一フォーマットのアイテム"""

    title: str
    url: str
    source_id: str
    fetched_at: datetime
    content: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """browse_source の output スキーマ準拠の辞書に変換"""
        return {
            "title": self.title,
            "url": self.url,
            "content": self.content,
            "source_id": self.source_id,
            "fetched_at": self.fetched_at.isoformat(),
            **self.extra,
        }


class BaseAdapter(ABC):
    """
    全ソースアダプタの基底クラス。

    サブクラスは fetch() を実装する。
    設定は config/sources/{source_id}.yaml から渡す。
    """

    def __init__(self, source_config: dict[str, Any]) -> None:
        self._config = source_config
        self._source_id: str = source_config["name"]

    @abstractmethod
    async def fetch(self, max_items: int = 20) -> list[FetchedItem]:
        """
        コンテンツを取得して FetchedItem リストを返す。

        Args:
            max_items: 最大取得件数

        Returns:
            FetchedItem のリスト（空リストも許容）
        """
        ...

    @property
    def source_id(self) -> str:
        return self._source_id

    @staticmethod
    def now_utc() -> datetime:
        """UTC 現在時刻を返す"""
        return datetime.now(timezone.utc)
