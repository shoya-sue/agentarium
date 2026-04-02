"""
skills/memory/store_knowledge_node.py — GraphRAG ノード保存 Skill

知識グラフ（Neo4j）にエンティティノードを保存する。
既存ノードは MERGE で更新（upsert）。

Skill 入出力スキーマ: config/skills/memory/store_knowledge_node.yaml
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from neo4j import AsyncGraphDatabase, AsyncDriver

logger = logging.getLogger(__name__)


class StoreKnowledgeNodeSkill:
    """
    store_knowledge_node Skill の実装。

    Neo4j に Knowledge ノードを MERGE で保存する。
    同一 entity_id は上書き更新（upsert）。
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
        知識グラフにエンティティノードを保存する。

        Args:
            params:
                entity_id (str): 一意識別子（必須）
                entity_type (str): ノード種別 (e.g., "concept", "person", "event")（必須）
                name (str): 表示名（必須）
                description (str | None): 説明文
                source_url (str | None): 出典 URL
                topics (list[str] | None): 関連トピック
                importance_score (float | None): 重要度スコア 0.0〜1.0

        Returns:
            {"entity_id": str, "stored_at": str, "created": bool}
            created=True: 新規作成, False: 更新
        """
        entity_id: str = params["entity_id"]
        entity_type: str = params["entity_type"]
        name: str = params["name"]

        if not entity_id.strip():
            raise ValueError("entity_id が空です")
        if not entity_type.strip():
            raise ValueError("entity_type が空です")
        if not name.strip():
            raise ValueError("name が空です")

        stored_at = datetime.now(timezone.utc).isoformat()

        node_props = {
            "entity_id": entity_id,
            "entity_type": entity_type,
            "name": name,
            "description": params.get("description", ""),
            "source_url": params.get("source_url", ""),
            "topics": params.get("topics") or [],
            "importance_score": float(params.get("importance_score") or 0.0),
            "stored_at": stored_at,
        }

        cypher = """
        MERGE (n:Knowledge {entity_id: $entity_id})
        ON CREATE SET n += $props, n.created_at = $stored_at
        ON MATCH SET n += $props, n.updated_at = $stored_at
        RETURN n.entity_id AS entity_id, (n.created_at = $stored_at) AS created
        """

        driver = await self._get_driver()
        async with driver.session() as session:
            result = await session.run(
                cypher,
                entity_id=entity_id,
                props=node_props,
                stored_at=stored_at,
            )
            record = await result.single()
            created = bool(record["created"]) if record else False

        logger.info(
            "store_knowledge_node: entity_id=%s type=%s created=%s",
            entity_id,
            entity_type,
            created,
        )

        return {
            "entity_id": entity_id,
            "stored_at": stored_at,
            "created": created,
        }

    async def close(self) -> None:
        """Neo4j ドライバを閉じる"""
        if self._driver is not None:
            await self._driver.close()
            self._driver = None
