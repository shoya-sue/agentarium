"""
tests/integration/test_rss_integration.py — RSS / HackerNews フィード統合テスト

browse_source Skill (RSS / hacker_news アダプタ) を実際のインターネット接続で検証する。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


# ──────────────────────────────────────────────
# browse_source / RSS アダプタ統合テスト
# ──────────────────────────────────────────────

class TestBrowseSourceRSSIntegration:
    """browse_source Skill (rss_feeds) をネットワーク接続でテストする"""

    @pytest.mark.asyncio
    async def test_rss_feeds_returns_items(self, config_dir: Path):
        """rss_feeds ソースが実際のフィードからアイテムを取得できる"""
        from skills.perception.browse_source import BrowseSourceSkill

        skill = BrowseSourceSkill(config_dir=config_dir)
        items = await skill.run({
            "source_id": "rss_feeds",
            "max_items": 5,
        })

        assert isinstance(items, list)
        # ネットワーク接続があれば最低 1 件取得できるはず
        # （フィード側の問題で 0 件になる可能性もあるので Warning 扱い）
        if len(items) == 0:
            pytest.xfail("RSS フィードからアイテムを取得できませんでした（ネットワーク問題の可能性）")

        # アイテムの構造確認
        first = items[0]
        assert "title" in first or "url" in first, (
            f"アイテムに title または url フィールドがありません: {first}"
        )

    @pytest.mark.asyncio
    async def test_hacker_news_returns_items(self, config_dir: Path):
        """hacker_news ソースが実際の HN API からアイテムを取得できる"""
        from skills.perception.browse_source import BrowseSourceSkill

        skill = BrowseSourceSkill(config_dir=config_dir)
        items = await skill.run({
            "source_id": "hacker_news",
            "max_items": 10,
        })

        assert isinstance(items, list)
        if len(items) == 0:
            pytest.xfail("Hacker News API からアイテムを取得できませんでした")

        # HN アイテムの構造確認
        first = items[0]
        assert "title" in first, f"HN アイテムに title がありません: {first}"
        # score や url があれば理想的
        print(f"\n[HN] 取得件数: {len(items)} — 先頭: {first.get('title', '?')[:60]}")

    @pytest.mark.asyncio
    async def test_max_items_respected(self, config_dir: Path):
        """max_items 上限が守られている"""
        from skills.perception.browse_source import BrowseSourceSkill

        skill = BrowseSourceSkill(config_dir=config_dir)
        items = await skill.run({
            "source_id": "hacker_news",
            "max_items": 3,
        })

        assert isinstance(items, list)
        assert len(items) <= 3, f"max_items=3 を超えています: {len(items)} 件"

    @pytest.mark.asyncio
    async def test_github_trending_returns_items(self, config_dir: Path):
        """github_trending ソースが GitHub から情報を取得できる"""
        from skills.perception.browse_source import BrowseSourceSkill

        skill = BrowseSourceSkill(config_dir=config_dir)
        items = await skill.run({
            "source_id": "github_trending",
            "max_items": 5,
        })

        assert isinstance(items, list)
        if len(items) == 0:
            pytest.xfail("GitHub Trending からアイテムを取得できませんでした")

        first = items[0]
        assert "title" in first or "name" in first or "url" in first, (
            f"GitHub アイテムに期待フィールドがありません: {first}"
        )
        print(f"\n[GitHub] 取得件数: {len(items)} — 先頭: {first}")
