"""
tests/skills/memory/test_graph_skills.py — GraphRAG スキルユニットテスト

Neo4j ドライバをモックして store_knowledge_node / store_knowledge_relation /
query_knowledge_graph の動作を検証する。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))


# ──────────────────────────────────────────────
# StoreKnowledgeNodeSkill
# ──────────────────────────────────────────────

class TestStoreKnowledgeNodeSkill:
    """StoreKnowledgeNodeSkill のテスト"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.memory.store_knowledge_node import StoreKnowledgeNodeSkill
        assert StoreKnowledgeNodeSkill is not None

    @pytest.mark.asyncio
    async def test_run_creates_node(self):
        """正常なパラメータでノードを保存できる"""
        from skills.memory.store_knowledge_node import StoreKnowledgeNodeSkill

        mock_record = {"entity_id": "concept:ai", "created": True}
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=mock_record)

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_driver = AsyncMock()
        mock_driver.session = MagicMock(return_value=mock_session)

        skill = StoreKnowledgeNodeSkill.__new__(StoreKnowledgeNodeSkill)
        skill._uri = "bolt://localhost:7687"
        skill._user = "neo4j"
        skill._password = "agentarium"
        skill._driver = mock_driver

        result = await skill.run({
            "entity_id": "concept:ai",
            "entity_type": "concept",
            "name": "Artificial Intelligence",
            "description": "AI の概念",
            "topics": ["AI", "technology"],
            "importance_score": 0.9,
        })

        assert result["entity_id"] == "concept:ai"
        assert "stored_at" in result
        assert "created" in result

    @pytest.mark.asyncio
    async def test_run_raises_on_empty_entity_id(self):
        """entity_id が空の場合は ValueError を送出する"""
        from skills.memory.store_knowledge_node import StoreKnowledgeNodeSkill

        skill = StoreKnowledgeNodeSkill.__new__(StoreKnowledgeNodeSkill)
        skill._driver = None

        with pytest.raises(ValueError, match="entity_id"):
            await skill.run({
                "entity_id": "",
                "entity_type": "concept",
                "name": "test",
            })

    @pytest.mark.asyncio
    async def test_run_raises_on_empty_name(self):
        """name が空の場合は ValueError を送出する"""
        from skills.memory.store_knowledge_node import StoreKnowledgeNodeSkill

        skill = StoreKnowledgeNodeSkill.__new__(StoreKnowledgeNodeSkill)
        skill._driver = None

        with pytest.raises(ValueError, match="name"):
            await skill.run({
                "entity_id": "concept:ai",
                "entity_type": "concept",
                "name": "  ",
            })


# ──────────────────────────────────────────────
# StoreKnowledgeRelationSkill
# ──────────────────────────────────────────────

class TestStoreKnowledgeRelationSkill:
    """StoreKnowledgeRelationSkill のテスト"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.memory.store_knowledge_relation import StoreKnowledgeRelationSkill
        assert StoreKnowledgeRelationSkill is not None

    @pytest.mark.asyncio
    async def test_run_creates_relation(self):
        """正常なパラメータでリレーションを保存できる"""
        from skills.memory.store_knowledge_relation import StoreKnowledgeRelationSkill

        mock_record = {"src_id": "concept:ai", "tgt_id": "concept:ml"}
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=mock_record)

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_driver = AsyncMock()
        mock_driver.session = MagicMock(return_value=mock_session)

        skill = StoreKnowledgeRelationSkill.__new__(StoreKnowledgeRelationSkill)
        skill._driver = mock_driver

        result = await skill.run({
            "source_id": "concept:ai",
            "target_id": "concept:ml",
            "relation_type": "RELATED_TO",
            "weight": 0.8,
        })

        assert result["source_id"] == "concept:ai"
        assert result["target_id"] == "concept:ml"
        assert result["relation_type"] == "RELATED_TO"
        assert "stored_at" in result

    @pytest.mark.asyncio
    async def test_invalid_relation_type_raises(self):
        """危険な文字を含む relation_type は ValueError"""
        from skills.memory.store_knowledge_relation import StoreKnowledgeRelationSkill

        skill = StoreKnowledgeRelationSkill.__new__(StoreKnowledgeRelationSkill)
        skill._driver = None

        with pytest.raises(ValueError, match="relation_type"):
            await skill.run({
                "source_id": "a",
                "target_id": "b",
                "relation_type": "RELATED_TO; DROP DATABASE",
            })

    @pytest.mark.asyncio
    async def test_node_not_found_raises(self):
        """対象ノードが存在しない場合は ValueError"""
        from skills.memory.store_knowledge_relation import StoreKnowledgeRelationSkill

        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_driver = AsyncMock()
        mock_driver.session = MagicMock(return_value=mock_session)

        skill = StoreKnowledgeRelationSkill.__new__(StoreKnowledgeRelationSkill)
        skill._driver = mock_driver

        with pytest.raises(ValueError, match="ノードが見つかりません"):
            await skill.run({
                "source_id": "nonexistent:a",
                "target_id": "nonexistent:b",
                "relation_type": "RELATED_TO",
            })


# ──────────────────────────────────────────────
# QueryKnowledgeGraphSkill
# ──────────────────────────────────────────────

class TestQueryKnowledgeGraphSkill:
    """QueryKnowledgeGraphSkill のテスト"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.memory.query_knowledge_graph import QueryKnowledgeGraphSkill
        assert QueryKnowledgeGraphSkill is not None

    @pytest.mark.asyncio
    async def test_raises_when_no_search_criteria(self):
        """検索条件が何もない場合は ValueError"""
        from skills.memory.query_knowledge_graph import QueryKnowledgeGraphSkill

        skill = QueryKnowledgeGraphSkill.__new__(QueryKnowledgeGraphSkill)
        skill._driver = None

        with pytest.raises(ValueError, match="entity_id"):
            await skill.run({})

    @pytest.mark.asyncio
    async def test_query_by_id_returns_nodes(self):
        """entity_id 指定でノードと関連を返す"""
        from skills.memory.query_knowledge_graph import QueryKnowledgeGraphSkill

        # nodes クエリのモック
        node_records = [
            {
                "entity_id": "concept:ai",
                "entity_type": "concept",
                "name": "AI",
                "description": "",
                "topics": ["AI"],
                "importance_score": 0.9,
                "source_url": "",
            }
        ]

        async def make_async_iter(records):
            """非同期イテレータを生成するヘルパー"""
            class AsyncIter:
                def __init__(self, items):
                    self._items = iter(items)
                def __aiter__(self):
                    return self
                async def __anext__(self):
                    try:
                        return next(self._items)
                    except StopIteration:
                        raise StopAsyncIteration
            return AsyncIter(records)

        call_count = [0]

        async def mock_run(*args, **kwargs):
            if call_count[0] == 0:
                result = await make_async_iter(node_records)
            else:
                result = await make_async_iter([])
            call_count[0] += 1
            return result

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(side_effect=mock_run)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_driver = AsyncMock()
        mock_driver.session = MagicMock(return_value=mock_session)

        skill = QueryKnowledgeGraphSkill.__new__(QueryKnowledgeGraphSkill)
        skill._driver = mock_driver

        result = await skill.run({"entity_id": "concept:ai"})

        assert "nodes" in result
        assert "relations" in result
        assert "total" in result

    @pytest.mark.asyncio
    async def test_query_by_text(self):
        """テキスト検索で結果を返す"""
        from skills.memory.query_knowledge_graph import QueryKnowledgeGraphSkill

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        async def empty_aiter():
            return
            yield

        mock_session.run = AsyncMock(return_value=empty_aiter())

        mock_driver = AsyncMock()
        mock_driver.session = MagicMock(return_value=mock_session)

        skill = QueryKnowledgeGraphSkill.__new__(QueryKnowledgeGraphSkill)
        skill._driver = mock_driver

        result = await skill.run({"query": "AI technology", "limit": 5})

        assert result["total"] == 0
        assert result["nodes"] == []
