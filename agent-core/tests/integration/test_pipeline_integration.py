"""
tests/integration/test_pipeline_integration.py — E2E パイプライン統合テスト

browse_source → store_episodic / store_semantic のフルパイプラインを
実際のサービス群（Qdrant + embed server + 外部フィード）に対してテストする。

これは main.py の run_once() と同等の処理を直接実行する。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from tests.integration.conftest import (
    QDRANT_URL,
    EMBED_URL,
    TEST_EPISODIC_COLLECTION,
    TEST_SEMANTIC_COLLECTION,
    requires_all_services,
)


@requires_all_services
class TestFullPipelineIntegration:
    """
    browse_source → store_episodic → store_semantic の
    フルパイプライン E2E テスト
    """

    @pytest.mark.asyncio
    async def test_full_pipeline_hacker_news(self, config_dir: Path):
        """
        Hacker News → Qdrant パイプラインの E2E テスト。

        1. browse_source (hacker_news) で記事取得
        2. store_episodic に実行ログを保存
        3. store_semantic に各記事コンテンツを保存
        4. recall_related で保存した内容を検索
        """
        import time
        from skills.perception.browse_source import BrowseSourceSkill
        from skills.memory.store_episodic import StoreEpisodicSkill
        from skills.memory.store_semantic import StoreSemanticSkill
        from skills.memory.recall_related import RecallRelatedSkill
        import skills.memory.store_semantic as store_mod
        import skills.memory.recall_related as recall_mod

        # テスト用コレクション名にオーバーライド
        original_store = store_mod.COLLECTION_NAME
        original_recall = recall_mod.COLLECTION_NAME
        store_mod.COLLECTION_NAME = TEST_SEMANTIC_COLLECTION
        recall_mod.COLLECTION_NAME = TEST_SEMANTIC_COLLECTION

        try:
            # ── Step 1: browse_source ──────────────────────────
            browse = BrowseSourceSkill(config_dir=config_dir)
            t_start = time.monotonic()
            items = await browse.run({
                "source_id": "hacker_news",
                "max_items": 5,
            })
            duration_ms = int((time.monotonic() - t_start) * 1000)

            assert isinstance(items, list)
            print(f"\n[Pipeline] browse_source: {len(items)} 件 ({duration_ms}ms)")

            if len(items) == 0:
                pytest.xfail("Hacker News API からアイテムを取得できませんでした")

            # ── Step 2: store_episodic ─────────────────────────
            episodic = StoreEpisodicSkill(qdrant_host="localhost", qdrant_port=6333)
            episodic.COLLECTION_NAME = TEST_EPISODIC_COLLECTION
            episodic._ensure_collection()

            ep_result = await episodic.run({
                "skill": "browse_source",
                "source": "hacker_news",
                "result_count": len(items),
                "duration_ms": duration_ms,
                "error": None,
            })
            assert "point_id" in ep_result
            print(f"[Pipeline] store_episodic: {ep_result['point_id']}")

            # ── Step 3: store_semantic（最初の 3 件のみ）─────────
            semantic = StoreSemanticSkill(
                qdrant_host="localhost",
                qdrant_port=6333,
                embed_url=EMBED_URL,
            )

            stored_ids = []
            for item in items[:3]:
                content = item.get("content") or item.get("title", "")
                if not content.strip():
                    continue
                sem_result = await semantic.run({
                    "content": content,
                    "source_url": item.get("url", ""),
                    "title": item.get("title", ""),
                })
                stored_ids.append(sem_result["point_id"])

            assert len(stored_ids) > 0
            print(f"[Pipeline] store_semantic: {len(stored_ids)} 件保存")

            # ── Step 4: recall_related で検索 ──────────────────
            recall = RecallRelatedSkill(
                qdrant_host="localhost",
                qdrant_port=6333,
                embed_url=EMBED_URL,
            )

            # HN は技術ニュースなので「プログラミング」で検索
            recall_results = await recall.run({
                "query": "programming technology software",
                "limit": 5,
                "score_threshold": 0.3,
            })

            assert isinstance(recall_results, list)
            print(f"[Pipeline] recall_related: {len(recall_results)} 件ヒット")
            if recall_results:
                print(f"[Pipeline] 最高スコア: {recall_results[0]['score']:.4f}")

            await semantic.close()
            await recall.close()

        finally:
            store_mod.COLLECTION_NAME = original_store
            recall_mod.COLLECTION_NAME = original_recall

    @pytest.mark.asyncio
    async def test_skill_trace_written(self, config_dir: Path, tmp_path: Path):
        """
        SkillEngine 経由の実行で SkillTrace JSON が data/traces/ に書き込まれる。
        """
        from core import SkillEngine
        from skills.memory.store_episodic import StoreEpisodicSkill

        traces_dir = tmp_path / "traces"
        traces_dir.mkdir()

        engine = SkillEngine(
            config_base=config_dir,
            traces_dir=traces_dir,
        )

        episodic = StoreEpisodicSkill(qdrant_host="localhost", qdrant_port=6333)
        episodic.COLLECTION_NAME = TEST_EPISODIC_COLLECTION
        episodic._ensure_collection()

        engine.register(
            "store_episodic",
            episodic.run,
            spec_path=config_dir / "skills" / "memory" / "store_episodic.yaml",
        )

        result = await engine.run(
            "store_episodic",
            {
                "skill": "trace_test",
                "source": "integration",
                "result_count": 1,
                "duration_ms": 50,
                "error": None,
            },
        )

        assert "point_id" in result

        # SkillTrace JSON ファイルが生成されているか確認
        trace_files = list(traces_dir.rglob("*.json"))
        assert len(trace_files) >= 1, "SkillTrace JSON が生成されていません"

        import json
        trace_data = json.loads(trace_files[0].read_text())
        assert trace_data["skill_name"] == "store_episodic"
        assert trace_data["status"] in ("success", "failure")
        assert "trace_id" in trace_data
        print(f"\n[Trace] {trace_files[0].name}: status={trace_data['status']} duration={trace_data.get('duration_ms')}ms")
