"""
adapters/rss.py — RSS フィードアダプタ

Phase 0 V4 検証済み: HN RSS 20件 / TechCrunch RSS 20件 OK
config/sources/rss_feeds.yaml (type: rss) に対応
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx

from .base import BaseAdapter, FetchedItem

logger = logging.getLogger(__name__)


class RSSAdapter(BaseAdapter):
    """
    RSS/Atom フィードアダプタ。

    複数フィードを並列取得し、since_hours 以内の記事のみ返す。
    """

    async def fetch(self, max_items: int = 20) -> list[FetchedItem]:
        """
        設定された全フィードから記事を取得する。

        Args:
            max_items: 全フィード合計の最大件数

        Returns:
            FetchedItem リスト（新しい順）
        """
        extraction = self._config.get("extraction", {})
        max_per_feed = extraction.get("max_items_per_feed", 20)
        since_hours = extraction.get("since_hours", 24)
        since_dt = datetime.now(timezone.utc) - timedelta(hours=since_hours)

        feeds: list[dict[str, Any]] = self._config.get("feeds", [])
        if not feeds:
            logger.warning("RSS フィードが設定されていません")
            return []

        # 全フィードを並列取得
        tasks = [
            self._fetch_feed(feed["url"], max_per_feed, since_dt)
            for feed in feeds
        ]
        results: list[list[FetchedItem]] = await asyncio.gather(*tasks, return_exceptions=False)

        # フラット化して新しい順にソート
        all_items: list[FetchedItem] = []
        for items in results:
            all_items.extend(items)

        all_items.sort(key=lambda x: x.fetched_at, reverse=True)
        return all_items[:max_items]

    async def _fetch_feed(
        self,
        feed_url: str,
        max_items: int,
        since_dt: datetime,
    ) -> list[FetchedItem]:
        """単一フィードを取得してパースする"""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    feed_url,
                    headers={"User-Agent": "Agentarium/1.0 (+RSS reader)"},
                    follow_redirects=True,
                )
                resp.raise_for_status()
                content = resp.text

            # feedparser は同期処理なのでスレッドプールで実行
            loop = asyncio.get_event_loop()
            parsed = await loop.run_in_executor(None, feedparser.parse, content)

            items: list[FetchedItem] = []
            fetched_at = self.now_utc()

            for entry in parsed.entries[:max_items]:
                item = self._entry_to_item(entry, fetched_at, since_dt)
                if item is not None:
                    items.append(item)

            logger.debug("RSS 取得: %s → %d 件", feed_url, len(items))
            return items

        except Exception as exc:
            logger.warning("RSS 取得エラー (%s): %s", feed_url, exc)
            return []

    def _entry_to_item(
        self,
        entry: Any,
        fetched_at: datetime,
        since_dt: datetime,
    ) -> FetchedItem | None:
        """feedparser エントリを FetchedItem に変換する"""
        title = getattr(entry, "title", "").strip()
        url = getattr(entry, "link", "").strip()
        if not title or not url:
            return None

        # 公開日時を取得（なければ fetched_at を使用）
        published_at = self._parse_published(entry, fetched_at)

        # since_dt より古い記事は除外
        if published_at < since_dt:
            return None

        # 本文（summary / content から取得）
        content = ""
        if hasattr(entry, "summary"):
            content = entry.summary or ""
        elif hasattr(entry, "content") and entry.content:
            content = entry.content[0].get("value", "")

        # HTML タグを簡易除去（BeautifulSoup は重いので正規表現で代替）
        import re
        content = re.sub(r"<[^>]+>", " ", content).strip()
        content = re.sub(r"\s+", " ", content)

        return FetchedItem(
            title=title,
            url=url,
            content=content[:2000],  # 最大 2000 文字
            source_id=self._source_id,
            fetched_at=fetched_at,
            extra={"published_at": published_at.isoformat()},
        )

    @staticmethod
    def _parse_published(entry: Any, fallback: datetime) -> datetime:
        """エントリの公開日時を UTC datetime として返す"""
        # published_parsed (time.struct_time) を優先
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                import time as time_module
                ts = time_module.mktime(entry.published_parsed)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                pass

        # published 文字列をパース
        if hasattr(entry, "published") and entry.published:
            try:
                dt = parsedate_to_datetime(entry.published)
                return dt.astimezone(timezone.utc)
            except Exception:
                pass

        return fallback
