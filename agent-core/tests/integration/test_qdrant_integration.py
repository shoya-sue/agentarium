"""
tests/integration/test_qdrant_integration.py — Qdrant 統合テスト

store_episodic / store_semantic / recall_related を
実際の Qdrant インスタンスに対してテストする。

前提: Qdrant が localhost:6333 で起動済み
      embed サーバーが localhost:8001 で起動済み
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from tests.integration.conftest import (
    TEST_EPISODIC_COLLECTION,
    TEST_SEMANTIC_COLLECTION,
    EMBED_URL,
    requires_qdrant,
    requires_all_services,
)


# ──────────────────────────────────────────────
# store_episodic 統合テスト
# ──────────────────────────────────────────────

@requires_qdrant
class TestStoreEpisodicIntegration:
    """StoreEpisodicSkill を実際の Qdrant に対してテストする"""

    def _make_skill(self):
        """テスト用コレクション名を使った StoreEpisodicSkill を生成する"""
        from skills.memory.store_episodic import StoreEpisodicSkill
        skill = StoreEpisodicSkill(qdrant_host="localhost", qdrant_port=6333)
        # テスト用コレクション名で上書き
        skill.COLLECTION_NAME = TEST_EPISODIC_COLLECTION
        skill._ensure_collection()
        return skill

    @pytest.mark.asyncio
    async def test_store_and_verify(self):
        """episodic 記憶が Qdrant に書き込まれる"""
        skill = self._make_skill()

        result = await skill.run({
            "skill": "browse_source",
            "source": "integration_test",
            "result_count": 5,
            "duration_ms": 1200,
            "error": None,
        })

        assert "point_id" in result
        assert "stored_at" in result
        assert isinstance(result["point_id"], str)
        assert len(result["point_id"]) == 36  # UUID 形式

    @pytest.mark.asyncio
    async def test_store_multiple_and_count(self):
        """複数の episodic 記憶を保存して件数を確認する"""
        from qdrant_client import QdrantClient

        skill = self._make_skill()
        client = QdrantClient(host="localhost", port=6333)

        # 現在の件数を取得
        before = client.count(collection_name=TEST_EPISODIC_COLLECTION).count

        # 3件保存
        for i in range(3):
            await skill.run({
                "skill": f"test_skill_{i}",
                "source": "integration_test",
                "result_count": i * 10,
                "duration_ms": 100 + i * 50,
                "error": None,
            })

        after = client.count(collection_name=TEST_EPISODIC_COLLECTION).count
        assert after >= before + 3

    @pytest.mark.asyncio
    async def test_store_with_error_field(self):
        """error フィールドが payload に保存される"""
        from qdrant_client import QdrantClient

        skill = self._make_skill()
        client = QdrantClient(host="localhost", port=6333)

        result = await skill.run({
            "skill": "browse_source",
            "source": "error_test",
            "result_count": 0,
            "duration_ms": 5000,
            "error": "タイムアウトエラーが発生しました",
        })

        # 保存した point を取得して payload 確認
        points = client.retrieve(
            collection_name=TEST_EPISODIC_COLLECTION,
            ids=[result["point_id"]],
            with_payload=True,
        )
        assert len(points) == 1
        assert points[0].payload["error"] == "タイムアウトエラーが発生しました"
        assert points[0].payload["skill"] == "browse_source"


# ──────────────────────────────────────────────
# store_semantic + recall_related 統合テスト
# ──────────────────────────────────────────────

@requires_all_services
class TestSemanticMemoryIntegration:
    """store_semantic → recall_related のフルパイプラインをテストする"""

    def _make_store_skill(self):
        """テスト用 StoreSemanticSkill を生成する"""
        from skills.memory.store_semantic import StoreSemanticSkill

        # StoreSemanticSkill のコレクション名を上書き
        import skills.memory.store_semantic as mod
        original = mod.COLLECTION_NAME
        mod.COLLECTION_NAME = TEST_SEMANTIC_COLLECTION

        skill = StoreSemanticSkill(
            qdrant_host="localhost",
            qdrant_port=6333,
            embed_url=EMBED_URL,
        )
        # コレクション名を元に戻す（グローバル変数の汚染防止）
        mod.COLLECTION_NAME = original
        skill._qdrant.collection_name = TEST_SEMANTIC_COLLECTION  # type: ignore
        return skill

    def _make_recall_skill(self):
        """テスト用 RecallRelatedSkill を生成する"""
        from skills.memory.recall_related import RecallRelatedSkill

        import skills.memory.recall_related as mod
        original = mod.COLLECTION_NAME
        mod.COLLECTION_NAME = TEST_SEMANTIC_COLLECTION

        skill = RecallRelatedSkill(
            qdrant_host="localhost",
            qdrant_port=6333,
            embed_url=EMBED_URL,
        )
        mod.COLLECTION_NAME = original
        return skill

    @pytest.mark.asyncio
    async def test_store_semantic_basic(self):
        """semantic 記憶が Qdrant に書き込まれる（embed ベクトル付き）"""
        from skills.memory.store_semantic import StoreSemanticSkill
        import skills.memory.store_semantic as mod

        original = mod.COLLECTION_NAME
        mod.COLLECTION_NAME = TEST_SEMANTIC_COLLECTION
        try:
            skill = StoreSemanticSkill(
                qdrant_host="localhost",
                qdrant_port=6333,
                embed_url=EMBED_URL,
            )

            result = await skill.run({
                "content": "Anthropic が Claude 4 を発表しました。新しい推論能力が向上しています。",
                "source_url": "https://example.com/claude4",
                "title": "Claude 4 発表",
                "topics": ["AI", "LLM", "Anthropic"],
            })

            assert "point_id" in result
            assert "stored_at" in result
            await skill.close()
        finally:
            mod.COLLECTION_NAME = original

    @pytest.mark.asyncio
    async def test_store_and_recall_pipeline(self):
        """
        store_semantic → recall_related の E2E パイプライン検証。

        AI 関連の記事を保存し、関連クエリで検索したときに
        保存したコンテンツが上位にヒットすることを確認する。
        """
        from skills.memory.store_semantic import StoreSemanticSkill
        from skills.memory.recall_related import RecallRelatedSkill
        import skills.memory.store_semantic as store_mod
        import skills.memory.recall_related as recall_mod

        # コレクション名を一時的にテスト用に変更
        original_store = store_mod.COLLECTION_NAME
        original_recall = recall_mod.COLLECTION_NAME
        store_mod.COLLECTION_NAME = TEST_SEMANTIC_COLLECTION
        recall_mod.COLLECTION_NAME = TEST_SEMANTIC_COLLECTION

        try:
            store = StoreSemanticSkill(
                qdrant_host="localhost",
                qdrant_port=6333,
                embed_url=EMBED_URL,
            )
            recall = RecallRelatedSkill(
                qdrant_host="localhost",
                qdrant_port=6333,
                embed_url=EMBED_URL,
            )

            # AI 記事を保存
            content_ai = (
                "大規模言語モデル（LLM）の研究が急速に進展しています。"
                "GPT-4やClaude、Geminiなどのモデルが実用化され、"
                "自然言語処理タスクで人間に近いパフォーマンスを発揮しています。"
            )
            store_result = await store.run({
                "content": content_ai,
                "source_url": "https://example.com/llm-news",
                "title": "LLM 研究の最新動向",
                "topics": ["AI", "LLM"],
            })

            assert "point_id" in store_result

            # 関連クエリで検索
            recall_results = await recall.run({
                "query": "大規模言語モデルの性能",
                "limit": 5,
                "score_threshold": 0.5,
            })

            # 少なくとも 1 件ヒットするはず
            assert isinstance(recall_results, list)
            assert len(recall_results) >= 1

            # 最上位のスコアが 0.5 以上
            top = recall_results[0]
            assert top["score"] >= 0.5
            assert "payload" in top
            assert "point_id" in top

            await store.close()
            await recall.close()

        finally:
            store_mod.COLLECTION_NAME = original_store
            recall_mod.COLLECTION_NAME = original_recall

    @pytest.mark.asyncio
    async def test_recall_empty_collection_returns_empty(self):
        """
        全く別のコレクション（空）に対する検索は空リストを返す。
        空コレクション向けの検索で例外が出ないことも確認する。
        """
        from skills.memory.recall_related import RecallRelatedSkill
        from qdrant_client import QdrantClient
        from qdrant_client.models import VectorParams, Distance

        empty_col = "test_integration_empty_semantic"
        client = QdrantClient(host="localhost", port=6333)

        # 空コレクション作成
        existing = [c.name for c in client.get_collections().collections]
        if empty_col not in existing:
            client.create_collection(
                collection_name=empty_col,
                vectors_config=VectorParams(size=768, distance=Distance.COSINE),
            )

        import skills.memory.recall_related as recall_mod
        original = recall_mod.COLLECTION_NAME
        recall_mod.COLLECTION_NAME = empty_col

        try:
            skill = RecallRelatedSkill(
                qdrant_host="localhost",
                qdrant_port=6333,
                embed_url=EMBED_URL,
            )
            results = await skill.run({
                "query": "存在しない記事の内容",
                "limit": 5,
                "score_threshold": 0.9,
            })
            assert results == []
            await skill.close()
        finally:
            recall_mod.COLLECTION_NAME = original
            # クリーンアップ
            try:
                client.delete_collection(empty_col)
            except Exception:
                pass
