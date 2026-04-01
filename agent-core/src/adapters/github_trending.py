"""
adapters/github_trending.py — GitHub Trending DOM パーサアダプタ

Phase 0 V4 検証済み: GitHub Trending 10件 OK
config/sources/github_trending.yaml (type: browser) に対応

注意: GitHub は rebrowser-playwright 不要（stealth_required: false）
通常の playwright で DOM 取得可能。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from rebrowser_playwright.async_api import async_playwright

from .base import BaseAdapter, FetchedItem

logger = logging.getLogger(__name__)

# GitHub Trending の公開 URL
GITHUB_TRENDING_URL = "https://github.com/trending"


class GitHubTrendingAdapter(BaseAdapter):
    """
    GitHub Trending ページを Playwright で DOM パースするアダプタ。

    stealth_required: false なので通常の Playwright を使用。
    article.Box-row セレクタでリポジトリ一覧を取得。
    """

    async def fetch(self, max_items: int = 20) -> list[FetchedItem]:
        """
        GitHub Trending からトレンドリポジトリを取得する。

        Args:
            max_items: 取得する最大件数（GitHub は通常 25件）

        Returns:
            FetchedItem リスト
        """
        params = self._config.get("parameters", {})
        since = params.get("since", "daily")
        language = params.get("language", "")

        url = GITHUB_TRENDING_URL
        query_parts = []
        if language:
            query_parts.append(f"l={language}")
        if since:
            query_parts.append(f"since={since}")
        if query_parts:
            url = f"{url}?{'&'.join(query_parts)}"

        selectors = self._config.get("extraction", {}).get("selectors", {})
        article_sel = selectors.get("article_container", "article.Box-row")
        title_sel = selectors.get("title", "h2 a")
        desc_sel = selectors.get("description", "p.col-9")
        lang_sel = selectors.get("language", "[itemprop='programmingLanguage']")
        stars_sel = selectors.get("stars_today", "span.d-inline-block.float-sm-right")

        fetched_at = self.now_utc()
        items: list[FetchedItem] = []

        # browser コンテナへの CDP 接続 URL（docker-compose 内は http://browser:9222）
        browser_url = os.environ.get("BROWSER_REMOTE_URL", "http://localhost:9222")

        try:
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(browser_url)
                page = await browser.new_page()

                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                articles = await page.query_selector_all(article_sel)

                for article in articles[:max_items]:
                    item = await self._parse_article(
                        article,
                        title_sel,
                        desc_sel,
                        lang_sel,
                        stars_sel,
                        fetched_at,
                    )
                    if item is not None:
                        items.append(item)

                await page.close()
                # browser.close() は呼ばない（共有リモートブラウザのため）

        except Exception as exc:
            logger.error("GitHub Trending 取得エラー: %s", exc)
            return []

        logger.info("GitHub Trending 取得完了: %d 件", len(items))
        return items

    async def _parse_article(
        self,
        article: Any,
        title_sel: str,
        desc_sel: str,
        lang_sel: str,
        stars_sel: str,
        fetched_at: Any,
    ) -> FetchedItem | None:
        """article.Box-row 要素を FetchedItem に変換する"""
        try:
            # タイトルと URL
            title_el = await article.query_selector(title_sel)
            if title_el is None:
                return None

            href = await title_el.get_attribute("href")
            if not href:
                return None

            url = f"https://github.com{href}"
            # リポジトリ名は "owner/repo" 形式（href の先頭 / を除く）
            repo_name = href.lstrip("/")
            title = repo_name

            # 説明
            desc_el = await article.query_selector(desc_sel)
            description = ""
            if desc_el:
                description = (await desc_el.inner_text()).strip()

            # 言語
            lang_el = await article.query_selector(lang_sel)
            language = ""
            if lang_el:
                language = (await lang_el.inner_text()).strip()

            # 今日のスター数
            stars_el = await article.query_selector(stars_sel)
            stars_today = ""
            if stars_el:
                stars_today = (await stars_el.inner_text()).strip()

            return FetchedItem(
                title=title,
                url=url,
                content=description,
                source_id=self._source_id,
                fetched_at=fetched_at,
                extra={
                    "language": language,
                    "stars_today": stars_today,
                },
            )

        except Exception as exc:
            logger.warning("GitHub Trending アイテムパースエラー: %s", exc)
            return None
