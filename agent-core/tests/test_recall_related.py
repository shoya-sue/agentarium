"""
tests/test_recall_related.py — RecallRelatedSkill ユニットテスト

Qdrant と埋め込みサーバーをモックして検証する。
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _mock_qdrant_hit(point_id: str, score: float, payload: dict) -> MagicMock:
    """Qdrant の ScoredPoint モックを作成する。"""
    hit = MagicMock()
    hit.id = point_id
    hit.score = score
    hit.payload = payload
    return hit


class TestRecallRelatedSkill:
    """RecallRelatedSkill の動作検証"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.memory.recall_related import RecallRelatedSkill
        assert RecallRelatedSkill is not None

    def _make_skill_with_mock_qdrant(self, search_return_value):
        """mock Qdrant クライアントを持つ RecallRelatedSkill を作成する。"""
        from skills.memory.recall_related import RecallRelatedSkill

        skill = RecallRelatedSkill()
        mock_qdrant = MagicMock()
        mock_qdrant.search = MagicMock(return_value=search_return_value)
        skill._qdrant = mock_qdrant
        return skill, mock_qdrant

    @pytest.mark.asyncio
    async def test_returns_list_of_results(self):
        """検索結果をリスト形式で返す"""
        mock_hits = [
            _mock_qdrant_hit("id-1", 0.95, {"title": "記事A", "topics": ["AI"]}),
            _mock_qdrant_hit("id-2", 0.82, {"title": "記事B", "topics": ["ML"]}),
        ]

        skill, _ = self._make_skill_with_mock_qdrant(mock_hits)

        with patch.object(skill, "_embed", new_callable=AsyncMock, return_value=[0.1] * 768):
            result = await skill.run({
                "query": "機械学習とは何か",
                "limit": 10,
            })

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["point_id"] == "id-1"
        assert result[0]["score"] == pytest.approx(0.95, abs=0.001)
        assert result[0]["payload"]["title"] == "記事A"

    @pytest.mark.asyncio
    async def test_empty_result_when_no_matches(self):
        """一致するアイテムがない場合は空リストを返す"""
        skill, _ = self._make_skill_with_mock_qdrant([])

        with patch.object(skill, "_embed", new_callable=AsyncMock, return_value=[0.0] * 768):
            result = await skill.run({"query": "存在しないトピック"})

        assert result == []

    @pytest.mark.asyncio
    async def test_score_rounded_to_4_decimal_places(self):
        """スコアが小数4桁に丸められている"""
        mock_hits = [_mock_qdrant_hit("id-1", 0.123456789, {"title": "test"})]
        skill, _ = self._make_skill_with_mock_qdrant(mock_hits)

        with patch.object(skill, "_embed", new_callable=AsyncMock, return_value=[0.1] * 768):
            result = await skill.run({"query": "test"})

        assert result[0]["score"] == 0.1235  # round(0.123456789, 4)

    @pytest.mark.asyncio
    async def test_default_limit_applied(self):
        """デフォルトの limit（5）が適用される"""
        from skills.memory.recall_related import RecallRelatedSkill

        skill = RecallRelatedSkill()
        mock_qdrant = MagicMock()
        captured_kwargs = {}

        def mock_search(**kwargs):
            captured_kwargs.update(kwargs)
            return []

        mock_qdrant.search = mock_search
        skill._qdrant = mock_qdrant

        with patch.object(skill, "_embed", new_callable=AsyncMock, return_value=[0.0] * 768):
            await skill.run({"query": "test"})

        assert "limit" in captured_kwargs
        assert captured_kwargs["limit"] == 5  # デフォルト値

    @pytest.mark.asyncio
    async def test_topic_filter_passed_to_qdrant(self):
        """topics フィルタが Qdrant に渡される"""
        from skills.memory.recall_related import RecallRelatedSkill

        skill = RecallRelatedSkill()
        mock_qdrant = MagicMock()
        captured_kwargs = {}

        def mock_search(**kwargs):
            captured_kwargs.update(kwargs)
            return []

        mock_qdrant.search = mock_search
        skill._qdrant = mock_qdrant

        with patch.object(skill, "_embed", new_callable=AsyncMock, return_value=[0.0] * 768):
            await skill.run({
                "query": "test",
                "filter": {"topics": ["AI", "ML"]},
            })

        assert "query_filter" in captured_kwargs
        assert captured_kwargs["query_filter"] is not None
