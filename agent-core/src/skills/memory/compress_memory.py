"""
skills/memory/compress_memory.py — 記憶圧縮 Skill

Qdrant コレクションをスキャンし、重要度が低い記憶を削除する。

Skill 入出力スキーマ: config/skills/memory/compress_memory.yaml
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION: str = "semantic"


class CompressMemorySkill:
    """
    compress_memory Skill の実装。

    Qdrant コレクションをスキャンし、importance_score が閾値を下回る
    記憶ポイントを削除する。
    """

    def __init__(
        self,
        qdrant_client: Any,
        importance_threshold: float = 0.3,
    ) -> None:
        self._qdrant = qdrant_client
        self._threshold = importance_threshold

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        記憶コレクションをスキャンして低重要度の記憶を削除する。

        Args:
            params:
                collection (str | None): 対象コレクション名（省略時: "semantic"）

        Returns:
            {
                "scanned": int,  # スキャンしたポイント数
                "deleted": int,  # 削除したポイント数
                "merged": int,   # マージしたポイント数（現フェーズでは常に 0）
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
        deleted = 0

        # 低重要度ポイントの ID を収集
        ids_to_delete: list[str] = []
        for point in points:
            payload = point.payload or {}
            raw_score = payload.get("importance_score")
            score: float = float(raw_score) if raw_score is not None else 0.0
            if score < self._threshold:
                ids_to_delete.append(point.id)

        # バッチ削除
        if ids_to_delete:
            from qdrant_client.models import PointIdsList
            self._qdrant.delete(
                collection_name=collection,
                points_selector=PointIdsList(points=ids_to_delete),
            )
            deleted = len(ids_to_delete)
            logger.info(
                "compress_memory: %d / %d 件削除 (collection=%s, threshold=%.2f)",
                deleted,
                scanned,
                collection,
                self._threshold,
            )

        return {
            "scanned": scanned,
            "deleted": deleted,
            "merged": 0,
        }
