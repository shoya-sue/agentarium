"""
skills/memory/store_procedural.py — 手順記憶保存 Skill

手順・ノウハウ（"〇〇をするには△△する"という手続き的知識）を
Qdrant の procedural コレクションに保存する。

embedding テキスト: procedure_name + context + steps を結合してベクトル化。

Skill 入出力スキーマ: config/skills/memory/store_procedural.yaml
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

logger = logging.getLogger(__name__)

# procedural コレクション名
COLLECTION_NAME = "procedural"

# multilingual-e5-base の次元数（Phase 0 V2 検証済み）
VECTOR_DIM = 768


class StoreProceduralSkill:
    """
    store_procedural Skill の実装。

    1. embed サーバー (POST /embed) でテキストをベクトル化
    2. Qdrant procedural コレクションに保存
    コレクションが存在しない場合は自動作成する。
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
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """procedural コレクションが存在しなければ作成する。"""
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
                logger.info("procedural コレクション作成完了（dim=%d）", VECTOR_DIM)
        except Exception as exc:
            logger.warning("procedural コレクション初期化エラー: %s", exc)

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

    def _build_embed_text(
        self,
        procedure_name: str,
        context: str,
        steps: list[str],
    ) -> str:
        """
        埋め込み対象テキストを構築する。

        procedure_name + context + steps を改行で結合する。

        Args:
            procedure_name: 手順名
            context: 手順が有効な文脈
            steps: 手順ステップリスト

        Returns:
            埋め込み用テキスト文字列
        """
        parts: list[str] = [procedure_name]
        if context:
            parts.append(context)
        parts.extend(steps)
        return "\n".join(parts)

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        手順・ノウハウを procedural コレクションに保存する。

        Args:
            params:
                procedure_name (str): 手順の名前（必須）
                steps (list[str]): 手順のステップリスト（必須）
                context (str | None): 手順が有効な文脈・前提条件
                outcome (str | None): 期待される結果
                tags (list[str] | None): タグリスト
                source_skill (str | None): この手順を学習したスキル名
                confidence (float | None): 信頼度 0.0〜1.0（デフォルト: 1.0）

        Returns:
            {
                "point_id": str,       # Qdrant に保存したポイントID
                "procedure_name": str, # 手順名
                "steps_count": int,    # ステップ数
                "collection": str,     # 保存先コレクション名
                "stored_at": str,      # 保存日時（ISO 8601）
            }
        """
        procedure_name: str = params["procedure_name"]
        steps: list[str] = params["steps"]
        context: str = params.get("context") or ""
        outcome: str = params.get("outcome") or ""
        tags: list[str] = params.get("tags") or []
        source_skill: str | None = params.get("source_skill")
        confidence: float = float(params.get("confidence", 1.0))

        if not procedure_name.strip():
            raise ValueError("procedure_name が空です")

        if not steps:
            raise ValueError("steps が空です")

        # 埋め込みテキスト構築
        embed_text = self._build_embed_text(
            procedure_name=procedure_name,
            context=context,
            steps=steps,
        )

        # 埋め込みベクトル取得
        vector = await self._embed(embed_text)

        stored_at = datetime.now(timezone.utc)
        point_id = str(uuid.uuid4())

        payload: dict[str, Any] = {
            "procedure_name": procedure_name,
            "steps": steps,
            "context": context,
            "outcome": outcome,
            "tags": tags,
            "source_skill": source_skill,
            "confidence": confidence,
            "stored_at": stored_at.isoformat(),
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
            "procedural 保存: name='%s' steps=%d confidence=%.2f point_id=%s",
            procedure_name,
            len(steps),
            confidence,
            point_id,
        )

        return {
            "point_id": point_id,
            "procedure_name": procedure_name,
            "steps_count": len(steps),
            "collection": COLLECTION_NAME,
            "stored_at": stored_at.isoformat(),
        }

    async def close(self) -> None:
        """HTTP クライアントを閉じる。"""
        await self._http.aclose()
