"""
skills/memory/query_knowledge_graph.py — GraphRAG クエリ Skill

Neo4j 知識グラフからエンティティとその関連ノードを検索する。
entity_id による直接取得と、name/topics によるテキスト検索をサポート。

Skill 入出力スキーマ: config/skills/memory/query_knowledge_graph.yaml
"""

from __future__ import annotations

import logging
from typing import Any

from neo4j import AsyncGraphDatabase, AsyncDriver

logger = logging.getLogger(__name__)

# 取得するリレーションの最大ホップ数
_DEFAULT_MAX_HOPS = 2
_DEFAULT_LIMIT = 10


class QueryKnowledgeGraphSkill:
    """
    query_knowledge_graph Skill の実装。

    1. entity_id 指定: 特定ノードとその近傍を取得
    2. name/topics 検索: テキストマッチで関連ノードを取得
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
        知識グラフからノードと関連を検索する。

        Args:
            params:
                entity_id (str | None): 直接取得するノードの entity_id
                query (str | None): name/description のテキスト検索クエリ
                topics (list[str] | None): トピックフィルタ
                entity_type (str | None): ノード種別フィルタ
                max_hops (int): 近傍ホップ数（デフォルト: 2）
                limit (int): 取得最大ノード数（デフォルト: 10）

        Returns:
            {
                "nodes": list[dict],      # マッチしたノードリスト
                "relations": list[dict],  # ノード間のリレーションリスト
                "total": int
            }
        """
        entity_id: str | None = params.get("entity_id")
        query: str | None = params.get("query")
        topics: list[str] | None = params.get("topics")
        entity_type: str | None = params.get("entity_type")
        max_hops: int = int(params.get("max_hops", _DEFAULT_MAX_HOPS))
        limit: int = int(params.get("limit", _DEFAULT_LIMIT))

        if not entity_id and not query and not topics:
            raise ValueError("entity_id, query, topics のいずれかは必須です")

        driver = await self._get_driver()
        async with driver.session() as session:
            if entity_id:
                nodes, relations = await self._query_by_id(
                    session, entity_id, max_hops, limit
                )
            else:
                nodes, relations = await self._query_by_text(
                    session, query or "", topics or [], entity_type, limit
                )

        logger.info(
            "query_knowledge_graph: entity_id=%s query='%s' nodes=%d relations=%d",
            entity_id,
            (query or "")[:40],
            len(nodes),
            len(relations),
        )

        return {
            "nodes": nodes,
            "relations": relations,
            "total": len(nodes),
        }

    async def _query_by_id(
        self,
        session: Any,
        entity_id: str,
        max_hops: int,
        limit: int,
    ) -> tuple[list[dict], list[dict]]:
        """entity_id で指定したノードとその近傍を取得する。"""
        # max_hops を 1〜3 に制限（パフォーマンス保護）
        hops = max(1, min(max_hops, 3))

        cypher = f"""
        MATCH path = (start:Knowledge {{entity_id: $entity_id}})-[*0..{hops}]-(related:Knowledge)
        WITH start, related, relationships(path) AS rels
        RETURN DISTINCT
            related.entity_id AS entity_id,
            related.entity_type AS entity_type,
            related.name AS name,
            related.description AS description,
            related.topics AS topics,
            related.importance_score AS importance_score,
            related.source_url AS source_url
        LIMIT $limit
        """
        result = await session.run(cypher, entity_id=entity_id, limit=limit)
        nodes = []
        async for record in result:
            nodes.append(dict(record))

        # リレーション取得
        rel_cypher = f"""
        MATCH (src:Knowledge {{entity_id: $entity_id}})-[r*1..{hops}]-(tgt:Knowledge)
        WITH src, r, tgt
        UNWIND r AS rel
        RETURN DISTINCT
            startNode(rel).entity_id AS source_id,
            endNode(rel).entity_id AS target_id,
            type(rel) AS relation_type,
            rel.weight AS weight,
            rel.description AS description
        LIMIT $limit
        """
        rel_result = await session.run(rel_cypher, entity_id=entity_id, limit=limit * 2)
        relations = []
        async for record in rel_result:
            relations.append(dict(record))

        return nodes, relations

    async def _query_by_text(
        self,
        session: Any,
        query: str,
        topics: list[str],
        entity_type: str | None,
        limit: int,
    ) -> tuple[list[dict], list[dict]]:
        """テキストクエリとトピックフィルタでノードを検索する。"""
        conditions = []
        params: dict[str, Any] = {"limit": limit}

        if query:
            conditions.append(
                "(toLower(n.name) CONTAINS toLower($query) OR toLower(n.description) CONTAINS toLower($query))"
            )
            params["query"] = query

        if topics:
            conditions.append("ANY(t IN $topics WHERE t IN n.topics)")
            params["topics"] = topics

        if entity_type:
            conditions.append("n.entity_type = $entity_type")
            params["entity_type"] = entity_type

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        cypher = f"""
        MATCH (n:Knowledge)
        {where_clause}
        RETURN
            n.entity_id AS entity_id,
            n.entity_type AS entity_type,
            n.name AS name,
            n.description AS description,
            n.topics AS topics,
            n.importance_score AS importance_score,
            n.source_url AS source_url
        ORDER BY n.importance_score DESC
        LIMIT $limit
        """
        result = await session.run(cypher, **params)
        nodes = []
        entity_ids = []
        async for record in result:
            nodes.append(dict(record))
            entity_ids.append(record["entity_id"])

        relations: list[dict] = []
        if len(entity_ids) >= 2:
            rel_cypher = """
            MATCH (src:Knowledge)-[r]->(tgt:Knowledge)
            WHERE src.entity_id IN $ids AND tgt.entity_id IN $ids
            RETURN
                src.entity_id AS source_id,
                tgt.entity_id AS target_id,
                type(r) AS relation_type,
                r.weight AS weight,
                r.description AS description
            """
            rel_result = await session.run(rel_cypher, ids=entity_ids)
            async for record in rel_result:
                relations.append(dict(record))

        return nodes, relations

    async def close(self) -> None:
        """Neo4j ドライバを閉じる"""
        if self._driver is not None:
            await self._driver.close()
            self._driver = None
