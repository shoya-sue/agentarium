"""
tests/test_recall_character_state.py — RecallCharacterStateSkill ユニットテスト

Qdrant クライアントをモックしてキャラクター状態取得ロジックを検証する。
Phase 3 Skill: character_state コレクションから最新の L3/L4/L5 状態を取得。
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _make_qdrant_mock_with_results(points: list) -> MagicMock:
    """検索結果を持つ QdrantClient のモックを作成する。"""
    mock = MagicMock()
    # scroll() が (points, next_page_offset) を返す形式
    mock.scroll.return_value = (points, None)
    return mock


def _make_qdrant_point(point_id: str, payload: dict) -> MagicMock:
    """Qdrant の Record/Point モックを作成する。"""
    point = MagicMock()
    point.id = point_id
    point.payload = payload
    return point


def _sample_params(state_type: str = "emotional") -> dict:
    """テスト用パラメータを返す。"""
    return {
        "character_name": "Zethi",
        "state_type": state_type,
    }


class TestRecallCharacterStateImport:
    """インポートテスト"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.memory.recall_character_state import RecallCharacterStateSkill
        assert RecallCharacterStateSkill is not None


class TestRecallCharacterStateDryRun:
    """dry_run モードのテスト"""

    @pytest.mark.asyncio
    async def test_dry_run_returns_not_found(self):
        """dry_run=True → found=False, reason='dry_run' が返る（Qdrant 未接続）"""
        from skills.memory.recall_character_state import RecallCharacterStateSkill

        mock_qdrant = _make_qdrant_mock_with_results([])
        with patch("skills.memory.recall_character_state.QdrantClient", return_value=mock_qdrant):
            skill = RecallCharacterStateSkill()

        params = _sample_params()
        params["dry_run"] = True
        result = await skill.run(params)

        assert result["found"] is False
        assert result["reason"] == "dry_run"

    @pytest.mark.asyncio
    async def test_dry_run_does_not_call_scroll(self):
        """dry_run=True → Qdrant の scroll が呼ばれない"""
        from skills.memory.recall_character_state import RecallCharacterStateSkill

        mock_qdrant = _make_qdrant_mock_with_results([])
        with patch("skills.memory.recall_character_state.QdrantClient", return_value=mock_qdrant):
            skill = RecallCharacterStateSkill()

        params = _sample_params()
        params["dry_run"] = True
        await skill.run(params)

        mock_qdrant.scroll.assert_not_called()


class TestRecallCharacterStateOutput:
    """正常系出力スキーマのテスト"""

    @pytest.mark.asyncio
    async def test_found_returns_correct_schema(self):
        """Qdrant に結果がある → found=True, state/stored_at/character_name/state_type が返る"""
        from skills.memory.recall_character_state import RecallCharacterStateSkill

        stored_state = {"joy": 0.8, "anger": 0.1}
        point = _make_qdrant_point(
            "test-uuid-001",
            {
                "character_name": "Zethi",
                "state_type": "emotional",
                "state": stored_state,
                "stored_at": "2026-04-01T12:00:00+00:00",
            },
        )
        mock_qdrant = _make_qdrant_mock_with_results([point])

        with patch("skills.memory.recall_character_state.QdrantClient", return_value=mock_qdrant):
            skill = RecallCharacterStateSkill()

        result = await skill.run(_sample_params("emotional"))

        assert result["found"] is True
        assert result["state"] == stored_state
        assert result["stored_at"] == "2026-04-01T12:00:00+00:00"
        assert result["character_name"] == "Zethi"
        assert result["state_type"] == "emotional"

    @pytest.mark.asyncio
    async def test_found_reason_is_none(self):
        """正常に見つかった場合、reason は None"""
        from skills.memory.recall_character_state import RecallCharacterStateSkill

        point = _make_qdrant_point(
            "test-uuid-001",
            {
                "character_name": "Zethi",
                "state_type": "trust",
                "state": {"discord": 0.7},
                "stored_at": "2026-04-01T10:00:00+00:00",
            },
        )
        mock_qdrant = _make_qdrant_mock_with_results([point])

        with patch("skills.memory.recall_character_state.QdrantClient", return_value=mock_qdrant):
            skill = RecallCharacterStateSkill()

        result = await skill.run(_sample_params("trust"))

        assert result["reason"] is None

    @pytest.mark.asyncio
    async def test_state_field_is_dict(self):
        """state フィールドが辞書型で返る"""
        from skills.memory.recall_character_state import RecallCharacterStateSkill

        point = _make_qdrant_point(
            "test-uuid-001",
            {
                "character_name": "Zethi",
                "state_type": "cognitive",
                "state": {"focus": 0.9, "fatigue": 0.2},
                "stored_at": "2026-04-01T09:00:00+00:00",
            },
        )
        mock_qdrant = _make_qdrant_mock_with_results([point])

        with patch("skills.memory.recall_character_state.QdrantClient", return_value=mock_qdrant):
            skill = RecallCharacterStateSkill()

        result = await skill.run(_sample_params("cognitive"))

        assert isinstance(result["state"], dict)


class TestRecallCharacterStateNotFound:
    """検索結果なしのテスト"""

    @pytest.mark.asyncio
    async def test_not_found_returns_false(self):
        """Qdrant に結果なし → found=False"""
        from skills.memory.recall_character_state import RecallCharacterStateSkill

        mock_qdrant = _make_qdrant_mock_with_results([])

        with patch("skills.memory.recall_character_state.QdrantClient", return_value=mock_qdrant):
            skill = RecallCharacterStateSkill()

        result = await skill.run(_sample_params())

        assert result["found"] is False

    @pytest.mark.asyncio
    async def test_not_found_state_is_none(self):
        """Qdrant に結果なし → state=None"""
        from skills.memory.recall_character_state import RecallCharacterStateSkill

        mock_qdrant = _make_qdrant_mock_with_results([])

        with patch("skills.memory.recall_character_state.QdrantClient", return_value=mock_qdrant):
            skill = RecallCharacterStateSkill()

        result = await skill.run(_sample_params())

        assert result["state"] is None

    @pytest.mark.asyncio
    async def test_not_found_stored_at_is_none(self):
        """Qdrant に結果なし → stored_at=None"""
        from skills.memory.recall_character_state import RecallCharacterStateSkill

        mock_qdrant = _make_qdrant_mock_with_results([])

        with patch("skills.memory.recall_character_state.QdrantClient", return_value=mock_qdrant):
            skill = RecallCharacterStateSkill()

        result = await skill.run(_sample_params())

        assert result["stored_at"] is None

    @pytest.mark.asyncio
    async def test_not_found_character_name_preserved(self):
        """結果なしでも character_name はパラメータと一致する"""
        from skills.memory.recall_character_state import RecallCharacterStateSkill

        mock_qdrant = _make_qdrant_mock_with_results([])

        with patch("skills.memory.recall_character_state.QdrantClient", return_value=mock_qdrant):
            skill = RecallCharacterStateSkill()

        result = await skill.run(_sample_params())

        assert result["character_name"] == "Zethi"
        assert result["state_type"] == "emotional"


class TestRecallCharacterStateValidation:
    """入力バリデーションのテスト"""

    @pytest.mark.asyncio
    async def test_empty_character_name_rejected(self):
        """character_name が空文字 → found=False, reason='empty_character_name'"""
        from skills.memory.recall_character_state import RecallCharacterStateSkill

        mock_qdrant = _make_qdrant_mock_with_results([])
        with patch("skills.memory.recall_character_state.QdrantClient", return_value=mock_qdrant):
            skill = RecallCharacterStateSkill()

        params = _sample_params()
        params["character_name"] = ""
        result = await skill.run(params)

        assert result["found"] is False
        assert result["reason"] == "empty_character_name"

    @pytest.mark.asyncio
    async def test_invalid_state_type_rejected(self):
        """state_type が無効値 → found=False, reason='invalid_state_type'"""
        from skills.memory.recall_character_state import RecallCharacterStateSkill

        mock_qdrant = _make_qdrant_mock_with_results([])
        with patch("skills.memory.recall_character_state.QdrantClient", return_value=mock_qdrant):
            skill = RecallCharacterStateSkill()

        params = _sample_params()
        params["state_type"] = "unknown_type"
        result = await skill.run(params)

        assert result["found"] is False
        assert result["reason"] == "invalid_state_type"

    @pytest.mark.asyncio
    async def test_missing_state_type_rejected(self):
        """state_type 未指定 → found=False, reason='invalid_state_type'"""
        from skills.memory.recall_character_state import RecallCharacterStateSkill

        mock_qdrant = _make_qdrant_mock_with_results([])
        with patch("skills.memory.recall_character_state.QdrantClient", return_value=mock_qdrant):
            skill = RecallCharacterStateSkill()

        params = {"character_name": "Zethi"}
        result = await skill.run(params)

        assert result["found"] is False
        assert result["reason"] == "invalid_state_type"
