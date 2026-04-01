"""
tests/test_store_procedural.py — StoreProceduralSkill ユニットテスト

Qdrant クライアントをモックして手順記憶保存ロジックを検証する。
"""

import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _make_qdrant_mock() -> MagicMock:
    """QdrantClient のモックを作成する。"""
    mock = MagicMock()
    # get_collections().collections はコレクション一覧を返す
    mock.get_collections.return_value = MagicMock(collections=[])
    mock.create_collection.return_value = None
    mock.upsert.return_value = None
    return mock


def _sample_params() -> dict:
    """テスト用パラメータを返す。"""
    return {
        "procedure_name": "HackerNewsから記事収集",
        "steps": [
            "browse_source で HN トップページを取得する",
            "filter_relevance で AI関連記事を選別する",
            "store_semantic で意味記憶に保存する",
        ],
        "context": "HN の AI関連記事を定期収集したい場合",
        "outcome": "AI関連記事が意味記憶に保存される",
        "tags": ["HN", "情報収集", "AI"],
        "source_skill": "browse_source",
        "confidence": 0.9,
    }


class TestStoreProceduralSkill:
    """StoreProceduralSkill の動作検証"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.memory.store_procedural import StoreProceduralSkill
        assert StoreProceduralSkill is not None

    @pytest.mark.asyncio
    async def test_returns_stored_result(self):
        """正常ケース: Qdrant に保存 → point_id, procedure_name, steps_count が返る"""
        from skills.memory.store_procedural import StoreProceduralSkill

        mock_qdrant = _make_qdrant_mock()
        with patch("skills.memory.store_procedural.QdrantClient", return_value=mock_qdrant):
            skill = StoreProceduralSkill()

        result = await skill.run(_sample_params())

        assert "point_id" in result
        assert "procedure_name" in result
        assert "steps_count" in result
        assert result["procedure_name"] == "HackerNewsから記事収集"

    @pytest.mark.asyncio
    async def test_steps_count_correct(self):
        """steps_count が steps リストの長さと一致する"""
        from skills.memory.store_procedural import StoreProceduralSkill

        mock_qdrant = _make_qdrant_mock()
        with patch("skills.memory.store_procedural.QdrantClient", return_value=mock_qdrant):
            skill = StoreProceduralSkill()

        params = _sample_params()
        result = await skill.run(params)

        assert result["steps_count"] == len(params["steps"])

    @pytest.mark.asyncio
    async def test_creates_collection_if_not_exists(self):
        """コレクション不在 → 自動作成される"""
        from skills.memory.store_procedural import StoreProceduralSkill

        mock_qdrant = _make_qdrant_mock()
        # コレクションが存在しない状態
        mock_qdrant.get_collections.return_value = MagicMock(collections=[])

        with patch("skills.memory.store_procedural.QdrantClient", return_value=mock_qdrant):
            skill = StoreProceduralSkill()

        await skill.run(_sample_params())

        # create_collection が呼ばれたことを確認
        mock_qdrant.create_collection.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_recreate_existing_collection(self):
        """コレクションが既存の場合は再作成しない"""
        from skills.memory.store_procedural import StoreProceduralSkill

        mock_qdrant = _make_qdrant_mock()
        # procedural コレクションが既存
        existing_col = MagicMock()
        existing_col.name = "procedural"
        mock_qdrant.get_collections.return_value = MagicMock(collections=[existing_col])

        with patch("skills.memory.store_procedural.QdrantClient", return_value=mock_qdrant):
            skill = StoreProceduralSkill()

        # create_collection は呼ばれない
        mock_qdrant.create_collection.assert_not_called()

    @pytest.mark.asyncio
    async def test_default_confidence_is_one(self):
        """confidence 未指定 → payload に 1.0 が入る"""
        from skills.memory.store_procedural import StoreProceduralSkill

        mock_qdrant = _make_qdrant_mock()
        captured_payload = {}

        def capture_upsert(collection_name, points):
            captured_payload.update(points[0].payload)

        mock_qdrant.upsert.side_effect = capture_upsert

        with patch("skills.memory.store_procedural.QdrantClient", return_value=mock_qdrant):
            skill = StoreProceduralSkill()

        params = {
            "procedure_name": "テスト手順",
            "steps": ["ステップ1"],
            # confidence は指定しない
        }
        await skill.run(params)

        assert captured_payload.get("confidence") == 1.0

    @pytest.mark.asyncio
    async def test_payload_contains_all_fields(self):
        """payload に必須フィールドが全て存在する"""
        from skills.memory.store_procedural import StoreProceduralSkill

        mock_qdrant = _make_qdrant_mock()
        captured_payload = {}

        def capture_upsert(collection_name, points):
            captured_payload.update(points[0].payload)

        mock_qdrant.upsert.side_effect = capture_upsert

        with patch("skills.memory.store_procedural.QdrantClient", return_value=mock_qdrant):
            skill = StoreProceduralSkill()

        await skill.run(_sample_params())

        # 必須フィールドの確認
        assert "procedure_name" in captured_payload
        assert "steps" in captured_payload
        assert "context" in captured_payload
        assert "outcome" in captured_payload
        assert "tags" in captured_payload
        assert "source_skill" in captured_payload
        assert "confidence" in captured_payload
        assert "stored_at" in captured_payload

    @pytest.mark.asyncio
    async def test_point_id_is_uuid_string(self):
        """point_id が UUID 文字列形式である"""
        from skills.memory.store_procedural import StoreProceduralSkill

        mock_qdrant = _make_qdrant_mock()
        with patch("skills.memory.store_procedural.QdrantClient", return_value=mock_qdrant):
            skill = StoreProceduralSkill()

        result = await skill.run(_sample_params())

        point_id = result["point_id"]
        assert isinstance(point_id, str)
        # UUID 形式か確認（例外が出なければ有効な UUID）
        parsed = uuid.UUID(point_id)
        assert str(parsed) == point_id

    @pytest.mark.asyncio
    async def test_collection_in_result(self):
        """結果に collection フィールドが含まれる"""
        from skills.memory.store_procedural import StoreProceduralSkill

        mock_qdrant = _make_qdrant_mock()
        with patch("skills.memory.store_procedural.QdrantClient", return_value=mock_qdrant):
            skill = StoreProceduralSkill()

        result = await skill.run(_sample_params())

        assert "collection" in result
        assert isinstance(result["collection"], str)

    @pytest.mark.asyncio
    async def test_stored_at_in_result(self):
        """結果に stored_at フィールドが含まれる"""
        from skills.memory.store_procedural import StoreProceduralSkill

        mock_qdrant = _make_qdrant_mock()
        with patch("skills.memory.store_procedural.QdrantClient", return_value=mock_qdrant):
            skill = StoreProceduralSkill()

        result = await skill.run(_sample_params())

        assert "stored_at" in result
        assert isinstance(result["stored_at"], str)

    @pytest.mark.asyncio
    async def test_qdrant_upsert_called(self):
        """Qdrant の upsert が呼ばれる"""
        from skills.memory.store_procedural import StoreProceduralSkill

        mock_qdrant = _make_qdrant_mock()
        with patch("skills.memory.store_procedural.QdrantClient", return_value=mock_qdrant):
            skill = StoreProceduralSkill()

        await skill.run(_sample_params())

        mock_qdrant.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_optional_fields_default_to_empty(self):
        """オプションフィールドが未指定の場合はデフォルト値が入る"""
        from skills.memory.store_procedural import StoreProceduralSkill

        mock_qdrant = _make_qdrant_mock()
        captured_payload = {}

        def capture_upsert(collection_name, points):
            captured_payload.update(points[0].payload)

        mock_qdrant.upsert.side_effect = capture_upsert

        with patch("skills.memory.store_procedural.QdrantClient", return_value=mock_qdrant):
            skill = StoreProceduralSkill()

        # 最小限のパラメータのみ
        await skill.run({
            "procedure_name": "最小パラメータ手順",
            "steps": ["ステップ1", "ステップ2"],
        })

        # オプションフィールドはデフォルト値
        assert captured_payload.get("context") == ""
        assert captured_payload.get("outcome") == ""
        assert captured_payload.get("tags") == []
        assert captured_payload.get("source_skill") is None or captured_payload.get("source_skill") == ""
