"""
tests/test_browse_source.py — BrowseSourceSkill ユニットテスト

HTTP リクエストは respx でモックする（ネットワーク不要）。
"""

import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

AGENTARIUM_ROOT = Path(__file__).parent.parent.parent  # agent-core/ の 1 つ上 = agentarium/
CONFIG_DIR = AGENTARIUM_ROOT / "config"


class TestBrowseSourceSkill:
    """BrowseSourceSkill の動作検証"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.perception.browse_source import BrowseSourceSkill
        assert BrowseSourceSkill is not None

    def test_unsupported_type_raises_value_error(self, tmp_path: Path):
        """未対応の source type で ValueError が発生する"""
        import yaml
        from skills.perception.browse_source import BrowseSourceSkill

        sources_dir = tmp_path / "sources"
        sources_dir.mkdir()
        (sources_dir / "unknown.yaml").write_text(
            yaml.dump({"name": "unknown", "type": "unknown_type"})
        )

        skill = BrowseSourceSkill(config_dir=tmp_path)

        import asyncio
        with pytest.raises(ValueError, match="未対応のソースタイプ"):
            asyncio.run(skill.run({"source_id": "unknown"}))

    def test_missing_source_raises_file_not_found(self):
        """存在しない source_id で FileNotFoundError が発生する"""
        from skills.perception.browse_source import BrowseSourceSkill
        import asyncio

        if not CONFIG_DIR.exists():
            pytest.skip("config/ が存在しません")

        skill = BrowseSourceSkill(config_dir=CONFIG_DIR)

        with pytest.raises(FileNotFoundError):
            asyncio.run(skill.run({"source_id": "nonexistent_source_xyz"}))

    @pytest.mark.asyncio
    async def test_output_schema_compliance(self):
        """browse_source の出力が output スキーマに準拠している"""
        from adapters.base import FetchedItem
        from skills.perception.browse_source import BrowseSourceSkill

        if not CONFIG_DIR.exists():
            pytest.skip("config/ が存在しません")

        skill = BrowseSourceSkill(config_dir=CONFIG_DIR)

        # HackerNewsAdapter をモック
        mock_items = [
            FetchedItem(
                title="テスト記事",
                url="https://example.com/1",
                content="",
                source_id="hacker_news",
                fetched_at=datetime.now(timezone.utc),
                extra={"score": 100},
            )
        ]

        with patch(
            "adapters.hn_api.HackerNewsAdapter.fetch",
            new_callable=AsyncMock,
            return_value=mock_items,
        ):
            result = await skill.run({"source_id": "hacker_news", "max_items": 5})

        assert isinstance(result, list)
        assert len(result) == 1

        item = result[0]
        # output スキーマの必須フィールド確認
        assert "title" in item
        assert "url" in item
        assert "source_id" in item
        assert "fetched_at" in item
        assert item["title"] == "テスト記事"
        assert item["source_id"] == "hacker_news"
