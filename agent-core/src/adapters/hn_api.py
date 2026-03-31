"""
adapters/hn_api.py — Hacker News Firebase API アダプタ

Phase 0 V4 検証済み: 500件取得 OK
config/sources/hacker_news.yaml (type: api) に対応
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .base import BaseAdapter, FetchedItem

logger = logging.getLogger(__name__)

# 同時接続数上限（HN API は軽量だが礼儀として制限）
_CONCURRENCY = 5


class HackerNewsAdapter(BaseAdapter):
    """
    Hacker News Firebase API 経由のアダプタ。

    ブラウザ不要。stealth_required: false。
    """

    HN_BASE_URL = "https://hacker-news.firebaseio.com/v0"

    async def fetch(self, max_items: int = 20) -> list[FetchedItem]:
        """
        HN トップストーリーを取得する。

        1. /topstories.json で ID リスト取得
        2. 上位 max_items 件を並列で /item/{id}.json から取得
        3. FetchedItem に変換

        Args:
            max_items: 取得するストーリー数（最大 30）

        Returns:
            FetchedItem リスト
        """
        extraction = self._config.get("extraction", {})
        actual_max = min(max_items, extraction.get("max_items", 30))

        async with httpx.AsyncClient(timeout=15.0) as client:
            # トップストーリー ID リスト取得
            resp = await client.get(f"{self.HN_BASE_URL}/topstories.json")
            resp.raise_for_status()
            story_ids: list[int] = resp.json()[:actual_max]

            # 並列でアイテム取得
            semaphore = asyncio.Semaphore(_CONCURRENCY)
            tasks = [
                self._fetch_item(client, semaphore, story_id)
                for story_id in story_ids
            ]
            raw_items: list[dict[str, Any] | None] = await asyncio.gather(*tasks)

        fetched_at = self.now_utc()
        items: list[FetchedItem] = []
        for raw in raw_items:
            if raw is None:
                continue
            item = self._to_fetched_item(raw, fetched_at)
            if item is not None:
                items.append(item)

        logger.info("HN 取得完了: %d 件", len(items))
        return items

    async def _fetch_item(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        item_id: int,
    ) -> dict[str, Any] | None:
        """単一アイテムを取得する"""
        async with semaphore:
            try:
                resp = await client.get(f"{self.HN_BASE_URL}/item/{item_id}.json")
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                logger.warning("HN アイテム取得エラー (id=%d): %s", item_id, exc)
                return None

    def _to_fetched_item(
        self,
        raw: dict[str, Any],
        fetched_at: Any,
    ) -> FetchedItem | None:
        """HN アイテム JSON を FetchedItem に変換する"""
        # story タイプのみ（comment, job, pollopt 等は除外）
        if raw.get("type") not in ("story", "ask", "show"):
            return None

        title = raw.get("title", "").strip()
        if not title:
            return None

        url = raw.get("url") or f"https://news.ycombinator.com/item?id={raw.get('id', '')}"

        return FetchedItem(
            title=title,
            url=url,
            content="",  # HN API は本文を提供しない
            source_id=self._source_id,
            fetched_at=fetched_at,
            extra={
                "score": raw.get("score", 0),
                "author": raw.get("by", ""),
                "comment_count": raw.get("descendants", 0),
                "hn_id": raw.get("id"),
            },
        )
