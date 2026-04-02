"""
skills/memory/store_knowledge_relation.py — GraphRAG リレーション保存 Skill

Neo4j の Knowledge ノード間に双方向リレーションを保存する。
既存リレーションは MERGE で更新（upsert）。

Skill 入出力スキーマ: config/skills/memory/store_knowledge_relation.yaml
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from neo4j import AsyncGraphDatabase, AsyncDriver

logger = logging.getLogger(__name__)

_SAFE_RELATION_RE = r'^[A-Z][A-Z0-9_]*$'


class StoreKnowledgeRelationSkill:
    """
    store_knowledge_relation Skill の実装。

    Neo4j で source_id → target_id の有向リレーションを MERGE で保存する。
    双方向リレーション（A→B かつ B→A）が必要な場合は 2 回呼び出す。
    """

    def __init__(
        self,
        neo4j_uri: str = "bolt://localhost:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "agentarium",
    ) -> None:
        self._uri = neo4j_uri
        self._user = neo4j_user
        self._password = neo4j_password
        self._driver: AsyncDriver | None = None

    async def _get_driver(self) -> AsyncDriver:
        if self._driver is None:
            self._driver = AsyncGraphDatabase.driver(
                self._uri,
                auth=(self._user, self._password),
            )
        return self._driver

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Knowledge ノード間にリレーションを保存する。

        Args:
            params:
                source_id (str): 起点ノードの entity_id（必須）
                target_id (str): 終点ノードの entity_id（必須）
                relation_type (str): リレーション種別（必須、例: "RELATED_TO", "CAUSES", "PART_OF"）
                description (str | None): リレーションの説明
                weight (float | None): 関係強度 0.0〜1.0（デフォルト: 1.0）
                bidirectional (bool): 双方向リレーションも作成するか（デフォルト: False）

        Returns:
            {"source_id": str, "target_id": str, "relation_type": str, "stored_at": str}
        """
        source_id: str = params["source_id"]
        target_id: str = params["target_id"]
        relation_type: str = params["relation_type"].upper().replace(" ", "_")
        description: str = params.get("description", "")
        weight: float = float(params.get("weight") or 1.0)
        bidirectional: bool = bool(params.get("bidirectional", False))

        if not source_id.strip():
            raise ValueError("source_id が空です")
        if not target_id.strip():
            raise ValueError("target_id が空です")
        if not relation_type.strip():
            raise ValueError("relation_type が空です")

        # relation_type は動的なため文字列補間（英大文字+_のみ許可でインジェクション防止）
        if not re.match(_SAFE_RELATION_RE, relation_type):
            raise ValueError(f"relation_type に使用できない文字が含まれています: {relation_type}")

        stored_at = datetime.now(timezone.utc).isoformat()

        cypher = f"""
        MATCH (src:Knowledge {{entity_id: $source_id}})
        MATCH (tgt:Knowledge {{entity_id: $target_id}})
        MERGE (src)-[r:{relation_type}]->(tgt)
        ON CREATE SET r.description = $description, r.weight = $weight, r.created_at = $stored_at
        ON MATCH SET r.description = $description, r.weight = $weight, r.updated_at = $stored_at
        RETURN src.entity_id AS src_id, tgt.entity_id AS tgt_id
        """

        driver = await self._get_driver()
        async with driver.session() as session:
            result = await session.run(
                cypher,
                source_id=source_id,
                target_id=target_id,
                description=description,
                weight=weight,
                stored_at=stored_at,
            )
            record = await result.single()
            if record is None:
                raise ValueError(
                    f"ノードが見つかりません: source_id={source_id} target_id={target_id}"
                )

            # 双方向リレーションの作成
            if bidirectional:
                reverse_cypher = f"""
                MATCH (src:Knowledge {{entity_id: $source_id}})
                MATCH (tgt:Knowledge {{entity_id: $target_id}})
                MERGE (tgt)-[r:{relation_type}]->(src)
                ON CREATE SET r.description = $description, r.weight = $weight, r.created_at = $stored_at
                ON MATCH SET r.description = $description, r.weight = $weight, r.updated_at = $stored_at
                """
                await session.run(
                    reverse_cypher,
                    source_id=source_id,
                    target_id=target_id,
                    description=description,
                    weight=weight,
                    stored_at=stored_at,
                )

        logger.info(
            "store_knowledge_relation: %s -[%s]-> %s bidirectional=%s",
            source_id,
            relation_type,
            target_id,
            bidirectional,
        )

        return {
            "source_id": source_id,
            "target_id": target_id,
            "relation_type": relation_type,
            "stored_at": stored_at,
        }

    async def close(self) -> None:
        """Neo4j ドライバを閉じる"""
        if self._driver is not None:
            await self._driver.close()
            self._driver = None
