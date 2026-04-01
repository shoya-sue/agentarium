"""
tests/test_compress_memory.py — CompressMemorySkill ユニットテスト

Qdrant クライアントをモックして記憶圧縮ロジックを検証する。
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _make_mock_point(point_id: str, payload: dict) -> MagicMock:
    """ScoredPoint 相当のモックを作成する。"""
    point = MagicMock()
    point.id = point_id
    point.payload = payload
    point.score = 0.95
    return point


def _make_qdrant_mock(points: list) -> MagicMock:
    """QdrantClient のモックを作成する。"""
    mock = MagicMock()
    # scroll で points を返す（(points, next_offset) タプル）
    mock.scroll.return_value = (points, None)
    mock.get_collection.return_value = MagicMock(points_count=len(points))
    mock.query_points.return_value = MagicMock(points=[])
    mock.delete.return_value = MagicMock()
    mock.upsert.return_value = MagicMock()
    return mock


def _sample_semantic_points(count: int = 5) -> list:
    """テスト用のセマンティック記憶ポイントを作成する。"""
    import uuid
    points = []
    for i in range(count):
        points.append(_make_mock_point(
            str(uuid.uuid4()),
            {
                "content_preview": f"AI トレンド記事 {i}: 最新の LLM 研究について",
                "source_url": f"https://example.com/article-{i}",
                "importance_score": 0.3 + i * 0.1,  # 0.3, 0.4, 0.5, 0.6, 0.7
                "stored_at": f"2026-03-0{i+1}T10:00:00+00:00",
                "topics": ["AI", "LLM"],
            }
        ))
    return points


class TestCompressMemorySkillImport:
    """インポートとクラス構造の確認"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.memory.compress_memory import CompressMemorySkill
        assert CompressMemorySkill is not None

    def test_instantiate_with_mock_qdrant(self):
        """QdrantClient モックでインスタンス化できる"""
        from skills.memory.compress_memory import CompressMemorySkill
        mock_qdrant = _make_qdrant_mock([])
        skill = CompressMemorySkill(qdrant_client=mock_qdrant)
        assert skill is not None

    def test_has_run_method(self):
        """run メソッドが存在する"""
        from skills.memory.compress_memory import CompressMemorySkill
        mock_qdrant = _make_qdrant_mock([])
        skill = CompressMemorySkill(qdrant_client=mock_qdrant)
        assert callable(skill.run)


class TestCompressMemorySkillOutput:
    """出力スキーマの検証"""

    def test_basic_output_structure(self):
        """出力に scanned / deleted / merged が含まれる"""
        from skills.memory.compress_memory import CompressMemorySkill
        mock_qdrant = _make_qdrant_mock(_sample_semantic_points(3))
        skill = CompressMemorySkill(qdrant_client=mock_qdrant)
        result = asyncio.run(
            skill.run({})
        )
        assert "scanned" in result
        assert "deleted" in result
        assert "merged" in result

    def test_scanned_count_is_int(self):
        """scanned が int である"""
        from skills.memory.compress_memory import CompressMemorySkill
        mock_qdrant = _make_qdrant_mock(_sample_semantic_points(4))
        skill = CompressMemorySkill(qdrant_client=mock_qdrant)
        result = asyncio.run(
            skill.run({})
        )
        assert isinstance(result["scanned"], int)
        assert result["scanned"] >= 0

    def test_deleted_count_is_int(self):
        """deleted が int である"""
        from skills.memory.compress_memory import CompressMemorySkill
        mock_qdrant = _make_qdrant_mock(_sample_semantic_points(3))
        skill = CompressMemorySkill(qdrant_client=mock_qdrant)
        result = asyncio.run(
            skill.run({})
        )
        assert isinstance(result["deleted"], int)
        assert result["deleted"] >= 0

    def test_merged_count_is_int(self):
        """merged が int である"""
        from skills.memory.compress_memory import CompressMemorySkill
        mock_qdrant = _make_qdrant_mock(_sample_semantic_points(3))
        skill = CompressMemorySkill(qdrant_client=mock_qdrant)
        result = asyncio.run(
            skill.run({})
        )
        assert isinstance(result["merged"], int)
        assert result["merged"] >= 0


class TestCompressMemorySkillLowImportanceDeletion:
    """低重要度記憶の削除検証"""

    def test_low_importance_points_deleted(self):
        """importance_score < threshold の点が削除される"""
        from skills.memory.compress_memory import CompressMemorySkill
        import uuid
        low_importance_point = _make_mock_point(
            str(uuid.uuid4()),
            {
                "content_preview": "重要度が低い記事",
                "source_url": "https://example.com/low",
                "importance_score": 0.1,  # しきい値以下
                "stored_at": "2026-01-01T00:00:00+00:00",
                "topics": [],
            }
        )
        mock_qdrant = _make_qdrant_mock([low_importance_point])
        skill = CompressMemorySkill(qdrant_client=mock_qdrant, importance_threshold=0.3)
        result = asyncio.run(
            skill.run({})
        )
        # 削除メソッドが呼ばれることを確認
        mock_qdrant.delete.assert_called()
        assert result["deleted"] >= 1

    def test_high_importance_points_kept(self):
        """importance_score >= threshold の点は保持される"""
        from skills.memory.compress_memory import CompressMemorySkill
        import uuid
        high_importance_point = _make_mock_point(
            str(uuid.uuid4()),
            {
                "content_preview": "重要度が高い記事",
                "source_url": "https://example.com/high",
                "importance_score": 0.9,
                "stored_at": "2026-04-01T00:00:00+00:00",
                "topics": ["AI"],
            }
        )
        mock_qdrant = _make_qdrant_mock([high_importance_point])
        skill = CompressMemorySkill(qdrant_client=mock_qdrant, importance_threshold=0.3)
        result = asyncio.run(
            skill.run({})
        )
        assert result["deleted"] == 0

    def test_empty_collection_no_deletion(self):
        """空コレクションでも正常に動作する"""
        from skills.memory.compress_memory import CompressMemorySkill
        mock_qdrant = _make_qdrant_mock([])
        skill = CompressMemorySkill(qdrant_client=mock_qdrant)
        result = asyncio.run(
            skill.run({})
        )
        assert result["scanned"] == 0
        assert result["deleted"] == 0
        assert result["merged"] == 0

    def test_none_importance_score_treated_as_zero(self):
        """importance_score が None の点はしきい値以下として削除される"""
        from skills.memory.compress_memory import CompressMemorySkill
        import uuid
        null_score_point = _make_mock_point(
            str(uuid.uuid4()),
            {
                "content_preview": "スコアなし記事",
                "source_url": "https://example.com/null",
                "importance_score": None,
                "stored_at": "2026-01-01T00:00:00+00:00",
                "topics": [],
            }
        )
        mock_qdrant = _make_qdrant_mock([null_score_point])
        skill = CompressMemorySkill(qdrant_client=mock_qdrant, importance_threshold=0.3)
        result = asyncio.run(
            skill.run({})
        )
        assert result["deleted"] >= 1


class TestCompressMemorySkillCollectionParam:
    """collection パラメータの検証"""

    def test_default_collection_is_semantic(self):
        """デフォルトの対象コレクションは semantic"""
        from skills.memory.compress_memory import CompressMemorySkill, DEFAULT_COLLECTION
        assert DEFAULT_COLLECTION == "semantic"

    def test_custom_collection_used(self):
        """collection パラメータでコレクション名を変更できる"""
        from skills.memory.compress_memory import CompressMemorySkill
        mock_qdrant = _make_qdrant_mock([])
        skill = CompressMemorySkill(qdrant_client=mock_qdrant)
        result = asyncio.run(
            skill.run({"collection": "episodic"})
        )
        # scroll がカスタムコレクション名で呼ばれることを確認
        call_args = mock_qdrant.scroll.call_args
        assert call_args[1].get("collection_name") == "episodic" or \
               (call_args[0] and call_args[0][0] == "episodic")
