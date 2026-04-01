"""
skills/memory/forget_low_value.py — 低価値記憶の忘却 Skill

Qdrant コレクションをスキャンし、アクセス数が少ない記憶を削除する。
エピソード記憶（episodic）を対象に、参照されていない記憶を自動的に忘れる。

Skill 入出力スキーマ: config/skills/memory/forget_low_value.yaml
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION: str = "episodic"


class ForgetLowValueSkill:
    """
    forget_low_value Skill の実装。

    Qdrant コレクションをスキャンし、access_count が閾値を下回る
    記憶ポイントを削除する。
    """

    def __init__(
        self,
        qdrant_client: Any,
        min_access_count: int = 1,
    ) -> None:
        self._qdrant = qdrant_client
        self._min_access_count = min_access_count

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        記憶コレクションをスキャンして低価値の記憶を削除する。

        Args:
            params:
                collection (str | None): 対象コレクション名（省略時: "episodic"）

        Returns:
            {
                "scanned": int,    # スキャンしたポイント数
                "forgotten": int,  # 削除したポイント数
            }
        """
        collection: str = params.get("collection") or DEFAULT_COLLECTION

        # コレクションの全ポイントを取得
        points, _ = self._qdrant.scroll(
            collection_name=collection,
            limit=10000,
            with_payload=True,
        )

        scanned = len(points)
        ids_to_delete: list[str] = []

        for point in points:
            payload = point.payload or {}
            raw_count = payload.get("access_count")
            count: int = int(raw_count) if raw_count is not None else 0
            if count < self._min_access_count:
                ids_to_delete.append(point.id)

        if ids_to_delete:
            from qdrant_client.models import PointIdsList
            self._qdrant.delete(
                collection_name=collection,
                points_selector=PointIdsList(points=ids_to_delete),
            )
            logger.info(
                "forget_low_value: %d / %d 件削除 (collection=%s, min_access_count=%d)",
                len(ids_to_delete),
                scanned,
                collection,
                self._min_access_count,
            )

        return {
            "scanned": scanned,
            "forgotten": len(ids_to_delete),
        }
