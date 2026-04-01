"""
tests/test_forget_low_value.py — ForgetLowValueSkill ユニットテスト

Qdrant クライアントをモックして低価値記憶の忘却ロジックを検証する。
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _make_mock_point(point_id: str, payload: dict) -> MagicMock:
    """ScoredPoint 相当のモックを作成する。"""
    point = MagicMock()
    point.id = point_id
    point.payload = payload
    point.score = 0.85
    return point


def _make_qdrant_mock(points: list) -> MagicMock:
    """QdrantClient のモックを作成する。"""
    mock = MagicMock()
    mock.scroll.return_value = (points, None)
    mock.get_collection.return_value = MagicMock(points_count=len(points))
    mock.delete.return_value = MagicMock()
    return mock


def _make_episodic_point(point_id: str, access_count: int, days_old: int = 10) -> MagicMock:
    """テスト用のエピソード記憶ポイントを作成する。"""
    return _make_mock_point(
        point_id,
        {
            "content_preview": f"過去の出来事 {point_id}",
            "access_count": access_count,
            "importance_score": 0.5,
            "stored_at": f"2026-03-{days_old:02d}T10:00:00+00:00",
            "topics": ["daily"],
        }
    )


class TestForgetLowValueSkillImport:
    """インポートとクラス構造の確認"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.memory.forget_low_value import ForgetLowValueSkill
        assert ForgetLowValueSkill is not None

    def test_default_collection_constant(self):
        """DEFAULT_COLLECTION 定数が存在する"""
        from skills.memory.forget_low_value import DEFAULT_COLLECTION
        assert DEFAULT_COLLECTION == "episodic"

    def test_instantiate_with_mock_qdrant(self):
        """QdrantClient モックでインスタンス化できる"""
        from skills.memory.forget_low_value import ForgetLowValueSkill
        mock_qdrant = _make_qdrant_mock([])
        skill = ForgetLowValueSkill(qdrant_client=mock_qdrant)
        assert skill is not None

    def test_has_run_method(self):
        """run メソッドが存在する"""
        from skills.memory.forget_low_value import ForgetLowValueSkill
        mock_qdrant = _make_qdrant_mock([])
        skill = ForgetLowValueSkill(qdrant_client=mock_qdrant)
        assert callable(skill.run)


class TestForgetLowValueSkillOutput:
    """出力スキーマの検証"""

    def test_basic_output_structure(self):
        """出力に scanned / forgotten が含まれる"""
        from skills.memory.forget_low_value import ForgetLowValueSkill
        mock_qdrant = _make_qdrant_mock([
            _make_episodic_point("id-1", access_count=5),
            _make_episodic_point("id-2", access_count=1),
        ])
        skill = ForgetLowValueSkill(qdrant_client=mock_qdrant)
        result = asyncio.run(skill.run({}))
        assert "scanned" in result
        assert "forgotten" in result

    def test_scanned_count_matches_points(self):
        """scanned がポイント数と一致する"""
        from skills.memory.forget_low_value import ForgetLowValueSkill
        points = [_make_episodic_point(f"id-{i}", access_count=3) for i in range(4)]
        mock_qdrant = _make_qdrant_mock(points)
        skill = ForgetLowValueSkill(qdrant_client=mock_qdrant)
        result = asyncio.run(skill.run({}))
        assert result["scanned"] == 4

    def test_forgotten_count_is_int(self):
        """forgotten が int である"""
        from skills.memory.forget_low_value import ForgetLowValueSkill
        mock_qdrant = _make_qdrant_mock([])
        skill = ForgetLowValueSkill(qdrant_client=mock_qdrant)
        result = asyncio.run(skill.run({}))
        assert isinstance(result["forgotten"], int)
        assert result["forgotten"] >= 0

    def test_empty_collection_returns_zeros(self):
        """空コレクションでも正常に動作する"""
        from skills.memory.forget_low_value import ForgetLowValueSkill
        mock_qdrant = _make_qdrant_mock([])
        skill = ForgetLowValueSkill(qdrant_client=mock_qdrant)
        result = asyncio.run(skill.run({}))
        assert result["scanned"] == 0
        assert result["forgotten"] == 0


class TestForgetLowValueSkillDeletion:
    """忘却ロジックの検証"""

    def test_low_access_count_point_forgotten(self):
        """access_count が閾値以下のポイントが削除される"""
        from skills.memory.forget_low_value import ForgetLowValueSkill
        # access_count=0 は最小閾値(1)以下 → 削除対象
        low_access_point = _make_episodic_point("low-id", access_count=0)
        mock_qdrant = _make_qdrant_mock([low_access_point])
        skill = ForgetLowValueSkill(qdrant_client=mock_qdrant, min_access_count=1)
        result = asyncio.run(skill.run({}))
        mock_qdrant.delete.assert_called()
        assert result["forgotten"] >= 1

    def test_high_access_count_point_kept(self):
        """access_count が閾値を超えるポイントは保持される"""
        from skills.memory.forget_low_value import ForgetLowValueSkill
        high_access_point = _make_episodic_point("high-id", access_count=10)
        mock_qdrant = _make_qdrant_mock([high_access_point])
        skill = ForgetLowValueSkill(qdrant_client=mock_qdrant, min_access_count=1)
        result = asyncio.run(skill.run({}))
        assert result["forgotten"] == 0

    def test_none_access_count_treated_as_zero(self):
        """access_count が None のポイントは 0 として扱われ削除される"""
        from skills.memory.forget_low_value import ForgetLowValueSkill
        null_point = _make_mock_point(
            "null-id",
            {
                "content_preview": "アクセス数なし",
                "access_count": None,
                "importance_score": 0.5,
                "stored_at": "2026-01-01T00:00:00+00:00",
                "topics": [],
            }
        )
        mock_qdrant = _make_qdrant_mock([null_point])
        skill = ForgetLowValueSkill(qdrant_client=mock_qdrant, min_access_count=1)
        result = asyncio.run(skill.run({}))
        assert result["forgotten"] >= 1

    def test_mixed_points_only_low_deleted(self):
        """アクセス数の混在ポイントで低いものだけ削除される"""
        from skills.memory.forget_low_value import ForgetLowValueSkill
        import uuid
        points = [
            _make_episodic_point(str(uuid.uuid4()), access_count=0),  # 削除対象
            _make_episodic_point(str(uuid.uuid4()), access_count=5),  # 保持
            _make_episodic_point(str(uuid.uuid4()), access_count=0),  # 削除対象
            _make_episodic_point(str(uuid.uuid4()), access_count=3),  # 保持
        ]
        mock_qdrant = _make_qdrant_mock(points)
        skill = ForgetLowValueSkill(qdrant_client=mock_qdrant, min_access_count=1)
        result = asyncio.run(skill.run({}))
        assert result["scanned"] == 4
        assert result["forgotten"] == 2


class TestForgetLowValueSkillCollectionParam:
    """collection パラメータの検証"""

    def test_default_collection_is_episodic(self):
        """デフォルトの対象コレクションは episodic"""
        from skills.memory.forget_low_value import DEFAULT_COLLECTION
        assert DEFAULT_COLLECTION == "episodic"

    def test_custom_collection_used(self):
        """collection パラメータでコレクション名を変更できる"""
        from skills.memory.forget_low_value import ForgetLowValueSkill
        mock_qdrant = _make_qdrant_mock([])
        skill = ForgetLowValueSkill(qdrant_client=mock_qdrant)
        result = asyncio.run(
            skill.run({"collection": "semantic"})
        )
        call_args = mock_qdrant.scroll.call_args
        assert call_args[1].get("collection_name") == "semantic" or \
               (call_args[0] and call_args[0][0] == "semantic")
