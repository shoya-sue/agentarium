"""
tests/test_store_character_state.py — StoreCharacterStateSkill ユニットテスト

Qdrant クライアントをモックしてキャラクター状態保存ロジックを検証する。
Phase 3 Skill: L3(emotional)/L4(cognitive)/L5(trust) 状態を character_state コレクションに保存。
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
    mock.get_collections.return_value = MagicMock(collections=[])
    mock.create_collection.return_value = None
    mock.upsert.return_value = None
    return mock


def _sample_params(state_type: str = "emotional") -> dict:
    """テスト用パラメータを返す。"""
    return {
        "character_name": "Zethi",
        "state_type": state_type,
        "state": {"joy": 0.8, "anger": 0.1, "sadness": 0.05},
    }


class TestStoreCharacterStateImport:
    """インポートテスト"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.memory.store_character_state import StoreCharacterStateSkill
        assert StoreCharacterStateSkill is not None


class TestStoreCharacterStateDryRun:
    """dry_run モードのテスト"""

    @pytest.mark.asyncio
    async def test_dry_run_returns_not_stored(self):
        """dry_run=True → stored=False, reason='dry_run' が返る（Qdrant 未接続）"""
        from skills.memory.store_character_state import StoreCharacterStateSkill

        mock_qdrant = _make_qdrant_mock()
        with patch("skills.memory.store_character_state.QdrantClient", return_value=mock_qdrant):
            skill = StoreCharacterStateSkill()

        params = _sample_params()
        params["dry_run"] = True
        result = await skill.run(params)

        assert result["stored"] is False
        assert result["reason"] == "dry_run"

    @pytest.mark.asyncio
    async def test_dry_run_does_not_call_upsert(self):
        """dry_run=True → Qdrant の upsert が呼ばれない"""
        from skills.memory.store_character_state import StoreCharacterStateSkill

        mock_qdrant = _make_qdrant_mock()
        with patch("skills.memory.store_character_state.QdrantClient", return_value=mock_qdrant):
            skill = StoreCharacterStateSkill()

        params = _sample_params()
        params["dry_run"] = True
        await skill.run(params)

        mock_qdrant.upsert.assert_not_called()


class TestStoreCharacterStateOutput:
    """正常系出力スキーマのテスト"""

    @pytest.mark.asyncio
    async def test_returns_stored_true(self):
        """正常ケース: stored=True が返る"""
        from skills.memory.store_character_state import StoreCharacterStateSkill

        mock_qdrant = _make_qdrant_mock()
        with patch("skills.memory.store_character_state.QdrantClient", return_value=mock_qdrant):
            skill = StoreCharacterStateSkill()

        result = await skill.run(_sample_params())

        assert result["stored"] is True

    @pytest.mark.asyncio
    async def test_returns_point_id_string(self):
        """point_id が UUID 文字列形式で返る"""
        from skills.memory.store_character_state import StoreCharacterStateSkill

        mock_qdrant = _make_qdrant_mock()
        with patch("skills.memory.store_character_state.QdrantClient", return_value=mock_qdrant):
            skill = StoreCharacterStateSkill()

        result = await skill.run(_sample_params())

        assert isinstance(result["point_id"], str)
        parsed = uuid.UUID(result["point_id"])
        assert str(parsed) == result["point_id"]

    @pytest.mark.asyncio
    async def test_returns_stored_at_iso8601(self):
        """stored_at が ISO8601 文字列で返る"""
        from skills.memory.store_character_state import StoreCharacterStateSkill

        mock_qdrant = _make_qdrant_mock()
        with patch("skills.memory.store_character_state.QdrantClient", return_value=mock_qdrant):
            skill = StoreCharacterStateSkill()

        result = await skill.run(_sample_params())

        assert isinstance(result["stored_at"], str)
        # ISO8601 形式であることを確認（パースできること）
        from datetime import datetime
        dt = datetime.fromisoformat(result["stored_at"])
        assert dt is not None

    @pytest.mark.asyncio
    async def test_returns_character_name(self):
        """character_name が返る"""
        from skills.memory.store_character_state import StoreCharacterStateSkill

        mock_qdrant = _make_qdrant_mock()
        with patch("skills.memory.store_character_state.QdrantClient", return_value=mock_qdrant):
            skill = StoreCharacterStateSkill()

        result = await skill.run(_sample_params())

        assert result["character_name"] == "Zethi"

    @pytest.mark.asyncio
    async def test_returns_state_type(self):
        """state_type が返る"""
        from skills.memory.store_character_state import StoreCharacterStateSkill

        mock_qdrant = _make_qdrant_mock()
        with patch("skills.memory.store_character_state.QdrantClient", return_value=mock_qdrant):
            skill = StoreCharacterStateSkill()

        result = await skill.run(_sample_params("cognitive"))

        assert result["state_type"] == "cognitive"

    @pytest.mark.asyncio
    async def test_upsert_called_once(self):
        """Qdrant の upsert が一回呼ばれる"""
        from skills.memory.store_character_state import StoreCharacterStateSkill

        mock_qdrant = _make_qdrant_mock()
        with patch("skills.memory.store_character_state.QdrantClient", return_value=mock_qdrant):
            skill = StoreCharacterStateSkill()

        await skill.run(_sample_params())

        mock_qdrant.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_state_types_accepted(self):
        """emotional / cognitive / trust の全種別が受け付けられる"""
        from skills.memory.store_character_state import StoreCharacterStateSkill

        mock_qdrant = _make_qdrant_mock()
        with patch("skills.memory.store_character_state.QdrantClient", return_value=mock_qdrant):
            skill = StoreCharacterStateSkill()

        for state_type in ["emotional", "cognitive", "trust"]:
            result = await skill.run(_sample_params(state_type))
            assert result["stored"] is True
            assert result["state_type"] == state_type


class TestStoreCharacterStateValidation:
    """入力バリデーションのテスト"""

    @pytest.mark.asyncio
    async def test_empty_character_name_rejected(self):
        """character_name が空文字 → stored=False, reason='empty_character_name'"""
        from skills.memory.store_character_state import StoreCharacterStateSkill

        mock_qdrant = _make_qdrant_mock()
        with patch("skills.memory.store_character_state.QdrantClient", return_value=mock_qdrant):
            skill = StoreCharacterStateSkill()

        params = _sample_params()
        params["character_name"] = ""
        result = await skill.run(params)

        assert result["stored"] is False
        assert result["reason"] == "empty_character_name"

    @pytest.mark.asyncio
    async def test_empty_state_rejected(self):
        """state が空辞書 → stored=False, reason='empty_state'"""
        from skills.memory.store_character_state import StoreCharacterStateSkill

        mock_qdrant = _make_qdrant_mock()
        with patch("skills.memory.store_character_state.QdrantClient", return_value=mock_qdrant):
            skill = StoreCharacterStateSkill()

        params = _sample_params()
        params["state"] = {}
        result = await skill.run(params)

        assert result["stored"] is False
        assert result["reason"] == "empty_state"

    @pytest.mark.asyncio
    async def test_invalid_state_type_rejected(self):
        """state_type が無効値 → stored=False, reason='invalid_state_type'"""
        from skills.memory.store_character_state import StoreCharacterStateSkill

        mock_qdrant = _make_qdrant_mock()
        with patch("skills.memory.store_character_state.QdrantClient", return_value=mock_qdrant):
            skill = StoreCharacterStateSkill()

        params = _sample_params()
        params["state_type"] = "invalid_type"
        result = await skill.run(params)

        assert result["stored"] is False
        assert result["reason"] == "invalid_state_type"

    @pytest.mark.asyncio
    async def test_missing_state_type_rejected(self):
        """state_type 未指定 → stored=False, reason='invalid_state_type'"""
        from skills.memory.store_character_state import StoreCharacterStateSkill

        mock_qdrant = _make_qdrant_mock()
        with patch("skills.memory.store_character_state.QdrantClient", return_value=mock_qdrant):
            skill = StoreCharacterStateSkill()

        params = {
            "character_name": "Zethi",
            "state": {"joy": 0.5},
            # state_type は未指定
        }
        result = await skill.run(params)

        assert result["stored"] is False
        assert result["reason"] == "invalid_state_type"
