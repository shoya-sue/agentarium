"""
skills/memory/recall_related.py — 関連記憶検索 Skill

クエリテキストを multilingual-e5-base でベクトル化し、
Qdrant semantic コレクションからコサイン類似度検索を行う。

Skill 入出力スキーマ: config/skills/memory/recall_related.yaml
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

logger = logging.getLogger(__name__)

COLLECTION_NAME = "semantic"


class RecallRelatedSkill:
    """
    recall_related Skill の実装。

    1. embed サーバー (POST /embed) でクエリをベクトル化
    2. Qdrant semantic コレクションからコサイン類似度検索
    """

    def __init__(
        self,
        qdrant_host: str = "localhost",
        qdrant_port: int = 6333,
        embed_url: str = "http://localhost:8001",
    ) -> None:
        self._qdrant = QdrantClient(host=qdrant_host, port=qdrant_port)
        self._embed_url = embed_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=30.0)

    async def _embed(self, text: str) -> list[float]:
        """
        embed サーバーにテキストを送ってベクトルを取得する。

        Args:
            text: クエリテキスト

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

    def _build_filter(self, filter_params: dict[str, Any] | None) -> Filter | None:
        """
        payload フィルタ条件を Qdrant Filter に変換する。

        現在サポートするフィルタ:
          - topics: list[str]  → topics フィールドに含まれるものを AND 条件で検索

        Args:
            filter_params: {"topics": ["AI", "LLM"]} 形式の辞書

        Returns:
            Qdrant Filter オブジェクト、またはフィルタなしの場合 None
        """
        if not filter_params:
            return None

        conditions = []

        topics = filter_params.get("topics")
        if topics:
            for topic in topics:
                conditions.append(
                    FieldCondition(
                        key="topics",
                        match=MatchValue(value=topic),
                    )
                )

        if not conditions:
            return None

        return Filter(must=conditions)

    async def run(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """
        クエリテキストに関連した記憶を semantic コレクションから検索する。

        Args:
            params:
                query (str): 検索クエリテキスト（必須）
                limit (int): 取得最大件数（デフォルト: 5）
                score_threshold (float): 類似度スコア下限 0.0〜1.0（デフォルト: 0.6）
                filter (dict | None): payload フィルタ条件

        Returns:
            list of {"point_id": int, "score": float, "payload": dict}
            スコア降順でソート済み。score_threshold 未満は除外済み。
        """
        query: str = params["query"]
        limit: int = int(params.get("limit", 5))
        score_threshold: float = float(params.get("score_threshold", 0.6))
        filter_params: dict[str, Any] | None = params.get("filter")

        if not query.strip():
            raise ValueError("query が空です")

        # クエリをベクトル化
        query_vector = await self._embed(query)

        # Qdrant でコサイン類似度検索
        qdrant_filter = self._build_filter(filter_params)

        results = self._qdrant.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_vector,
            limit=limit,
            score_threshold=score_threshold,
            query_filter=qdrant_filter,
            with_payload=True,
        )

        output = [
            {
                "point_id": hit.id,
                "score": round(float(hit.score), 4),
                "payload": hit.payload or {},
            }
            for hit in results
        ]

        top_score = output[0]["score"] if output else 0.0
        logger.info(
            "recall_related: query='%s...' hits=%d top_score=%.4f",
            query[:40],
            len(output),
            top_score,
        )

        return output

    async def close(self) -> None:
        """HTTP クライアントを閉じる"""
        await self._http.aclose()
