"""
skills/memory/store_semantic.py — semantic 記憶保存 Skill

収集コンテンツを multilingual-e5-base で埋め込みベクトル化して
Qdrant semantic コレクションに保存する。

Phase 0 V2 検証済み: multilingual-e5-base 関連 avg 0.810（768次元）
Phase 0 V3 検証済み: Qdrant 書き込み 11ms
Skill 入出力スキーマ: config/skills/memory/store_semantic.yaml
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

from models.llm import LLMClient

logger = logging.getLogger(__name__)

VECTOR_DIM = 768        # multilingual-e5-base の次元数
COLLECTION_NAME = "semantic"


class StoreSemanticSkill:
    """
    store_semantic Skill の実装。

    1. embed サーバー (POST /embed) でテキストをベクトル化
    2. Qdrant semantic コレクションに保存
    """

    def __init__(
        self,
        qdrant_host: str = "localhost",
        qdrant_port: int = 6333,
        embed_url: str = "http://localhost:8001",
        llm_client: LLMClient | None = None,
    ) -> None:
        self._qdrant = QdrantClient(host=qdrant_host, port=qdrant_port)
        self._embed_url = embed_url.rstrip("/")
        self._llm = llm_client
        self._http = httpx.AsyncClient(timeout=30.0)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """semantic コレクションが存在しなければ作成する"""
        try:
            existing = [c.name for c in self._qdrant.get_collections().collections]
            if COLLECTION_NAME not in existing:
                self._qdrant.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(
                        size=VECTOR_DIM,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("semantic コレクション作成完了（dim=%d）", VECTOR_DIM)
        except Exception as exc:
            logger.warning("semantic コレクション初期化エラー: %s", exc)

    async def _embed(self, text: str) -> list[float]:
        """
        embed サーバーにテキストを送ってベクトルを取得する。

        Args:
            text: 埋め込み対象テキスト

        Returns:
            768 次元の float リスト

        Raises:
            RuntimeError: embed サーバーが応答しない場合
        """
        resp = await self._http.post(
            f"{self._embed_url}/embed",
            json={"texts": [text]},
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings: list[list[float]] = data["embeddings"]
        if not embeddings:
            raise RuntimeError("embed サーバーが空のレスポンスを返しました")
        return embeddings[0]

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        コンテンツを埋め込みベクトル化して semantic コレクションに保存する。

        Args:
            params:
                content (str): 保存するテキストコンテンツ（必須）
                source_url (str): 出典 URL（必須）
                title (str | None): タイトル
                topics (list[str] | None): トピックリスト
                importance_score (float | None): 重要度スコア 0.0〜1.0
                facts (list | None): 抽出済み事実リスト

        Returns:
            {"point_id": str, "stored_at": str}
        """
        content: str = params["content"]
        source_url: str = params["source_url"]

        if not content.strip():
            raise ValueError("content が空です")

        # 埋め込みベクトル取得
        vector = await self._embed(content)

        stored_at = datetime.now(timezone.utc)
        point_id = str(uuid.uuid4())

        payload: dict[str, Any] = {
            "source_url": source_url,
            "title": params.get("title", ""),
            "topics": params.get("topics") or [],
            "importance_score": params.get("importance_score"),
            "facts": params.get("facts") or [],
            "stored_at": stored_at.isoformat(),
            # 全文も payload に保存（再利用のため）
            "content_preview": content[:500],
        }

        self._qdrant.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            ],
        )

        logger.info(
            "semantic 保存: url=%s importance=%.2f point_id=%s",
            source_url[:60],
            payload.get("importance_score") or 0.0,
            point_id,
        )

        return {"point_id": point_id, "stored_at": stored_at.isoformat()}

    async def close(self) -> None:
        """HTTP クライアントを閉じる"""
        await self._http.aclose()
