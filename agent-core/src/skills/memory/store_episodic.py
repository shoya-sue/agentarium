"""
skills/memory/store_episodic.py — episodic 記憶保存 Skill

Skill 実行ログ・行動記録を Qdrant episodic コレクションに保存する。

Phase 0 V3 検証済み: Qdrant 書き込み 11ms / 検索 4.9ms
episodic コレクションはベクトルなし（メタデータ検索のみ）。
Skill 入出力スキーマ: config/skills/memory/store_episodic.yaml
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    CollectionInfo,
)

logger = logging.getLogger(__name__)

# episodic コレクションはベクトルなし → ダミーベクトル 1次元で代用
# Qdrant はベクトルなしコレクションをサポートしているが
# qdrant-client の sparse vector API は複雑なためシンプルな実装を優先
_DUMMY_VECTOR_SIZE = 1


class StoreEpisodicSkill:
    """
    store_episodic Skill の実装。

    Qdrant episodic コレクションへのメタデータ保存。
    ベクトルは使わず payload のみで検索（フィルタベース）。
    """

    COLLECTION_NAME = "episodic"

    def __init__(self, qdrant_host: str = "localhost", qdrant_port: int = 6333) -> None:
        self._client = QdrantClient(host=qdrant_host, port=qdrant_port)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """episodic コレクションが存在しなければ作成する"""
        try:
            existing = [c.name for c in self._client.get_collections().collections]
            if self.COLLECTION_NAME not in existing:
                self._client.create_collection(
                    collection_name=self.COLLECTION_NAME,
                    vectors_config=VectorParams(
                        size=_DUMMY_VECTOR_SIZE,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("episodic コレクション作成完了")
        except Exception as exc:
            logger.warning("episodic コレクション初期化エラー: %s", exc)

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        実行ログを episodic コレクションに保存する。

        Args:
            params:
                skill (str): 実行した Skill 名
                source (str): 情報源 ID
                result_count (int): 結果件数
                duration_ms (int): 実行時間（ms）
                error (str | None): エラーメッセージ
                metadata (dict | None): 追加メタデータ

        Returns:
            {"point_id": str, "stored_at": str}
        """
        stored_at = datetime.now(timezone.utc)
        point_id = str(uuid.uuid4())

        payload: dict[str, Any] = {
            "timestamp": stored_at.isoformat(),
            "skill": params["skill"],
            "source": params["source"],
            "result_count": int(params["result_count"]),
            "duration_ms": int(params["duration_ms"]),
            "error": params.get("error"),
            "metadata": params.get("metadata") or {},
        }

        self._client.upsert(
            collection_name=self.COLLECTION_NAME,
            points=[
                PointStruct(
                    id=point_id,
                    vector=[0.0],  # episodic はダミーベクトル
                    payload=payload,
                )
            ],
        )

        logger.info(
            "episodic 保存: skill=%s source=%s point_id=%s",
            params["skill"],
            params["source"],
            point_id,
        )

        return {"point_id": point_id, "stored_at": stored_at.isoformat()}
