"""
skills/memory/store_character_state.py — キャラクター状態保存 Skill

L3(emotional)/L4(cognitive)/L5(trust) キャラクター状態を
Qdrant character_state コレクションに保存する。

store_episodic と同様に 1D ダミーベクトル [0.0] を使用し、
メタデータ検索（フィルタベース）のみで運用する。

Phase 3 Skill
Skill 入出力スキーマ: config/skills/memory/store_character_state.yaml
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
)

logger = logging.getLogger(__name__)

# character_state コレクションはベクトルなし → ダミーベクトル 1次元で代用
_DUMMY_VECTOR_SIZE = 1

# 有効な state_type の一覧（L3/L4/L5 に対応）
_VALID_STATE_TYPES = {"emotional", "cognitive", "trust"}


class StoreCharacterStateSkill:
    """
    store_character_state Skill の実装。

    Qdrant character_state コレクションへキャラクター状態を保存する。
    ベクトルは使わず payload のみで検索（フィルタベース）。
    """

    COLLECTION_NAME = "character_state"

    def __init__(self, qdrant_host: str = "localhost", qdrant_port: int = 6333) -> None:
        self._client = QdrantClient(host=qdrant_host, port=qdrant_port)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """character_state コレクションが存在しなければ作成する。"""
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
                logger.info("character_state コレクション作成完了")
        except Exception as exc:
            logger.warning("character_state コレクション初期化エラー: %s", exc)

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        キャラクター状態を character_state コレクションに保存する。

        Args:
            params:
                character_name (str): キャラクター名
                state_type (str): 状態種別 ("emotional" | "cognitive" | "trust")
                state (dict): 保存する状態辞書
                dry_run (bool): True の場合は保存を行わない

        Returns:
            {
                "stored": bool,
                "point_id": str,
                "stored_at": str,       # ISO8601 形式
                "character_name": str,
                "state_type": str,
                "reason": str | None,
            }
        """
        character_name: str = params.get("character_name", "")
        state_type: str = params.get("state_type", "")
        state: dict = params.get("state", {})
        dry_run: bool = params.get("dry_run", False)

        # ---- バリデーション ----
        if not character_name:
            return self._failure("empty_character_name", character_name, state_type)

        if state_type not in _VALID_STATE_TYPES:
            return self._failure("invalid_state_type", character_name, state_type)

        if not state:
            return self._failure("empty_state", character_name, state_type)

        # ---- dry_run モード ----
        if dry_run:
            return self._failure("dry_run", character_name, state_type)

        # ---- Qdrant 保存 ----
        stored_at = datetime.now(timezone.utc)
        point_id = str(uuid.uuid4())

        payload: dict[str, Any] = {
            "character_name": character_name,
            "state_type": state_type,
            "state": json.dumps(state, ensure_ascii=False),
            "stored_at": stored_at.isoformat(),
        }

        self._client.upsert(
            collection_name=self.COLLECTION_NAME,
            points=[
                PointStruct(
                    id=point_id,
                    vector=[0.0],  # character_state はダミーベクトル
                    payload=payload,
                )
            ],
        )

        logger.info(
            "character_state 保存: character=%s type=%s point_id=%s",
            character_name,
            state_type,
            point_id,
        )

        return {
            "stored": True,
            "point_id": point_id,
            "stored_at": stored_at.isoformat(),
            "character_name": character_name,
            "state_type": state_type,
            "reason": None,
        }

    def _failure(
        self, reason: str, character_name: str, state_type: str
    ) -> dict[str, Any]:
        """バリデーション失敗または dry_run 時の応答を返す。"""
        return {
            "stored": False,
            "point_id": "",
            "stored_at": "",
            "character_name": character_name,
            "state_type": state_type,
            "reason": reason,
        }
