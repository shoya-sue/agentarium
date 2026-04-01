"""
adapters/news_browser.py — 汎用ニュースサイト ブラウザアダプタ

Yahoo ニュース / Google News / NewsPicks など、
stealth_required: false の type: browser ソースを
config/sources/*.yaml の selectors 設定に従って DOM パースする汎用アダプタ。

対応ソース:
  - yahoo_news  (config/sources/yahoo_news.yaml)
  - google_news (config/sources/google_news.yaml)
  - newspicks   (config/sources/newspicks.yaml)

Phase 0 検証: stealth 不要なサイトは通常の Playwright で取得可能。
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from rebrowser_playwright.async_api import async_playwright, ElementHandle

from .base import BaseAdapter, FetchedItem

logger = logging.getLogger(__name__)

# HTML タグ除去パターン
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """HTML タグを除去する"""
    return _HTML_TAG_PATTERN.sub("", text).strip()


class NewsBrowserAdapter(BaseAdapter):
    """
    汎用ニュースサイトブラウザアダプタ。

    config/sources/*.yaml の extraction.selectors 設定に従って DOM をパースする。
    stealth_required: false を前提とし、通常の Playwright を使用する。

    設定例 (yahoo_news.yaml):
        extraction:
          selectors:
            article_container: ".newsFeed_item"
            title: ".newsFeed_item_title"
            url: "a[href]"
            summary: ".newsFeed_item_sub"
    """

    async def fetch(self, max_items: int = 20) -> list[FetchedItem]:
        """
        ニュースサイトから記事リストを取得する。

        Args:
            max_items: 取得する最大件数

        Returns:
            FetchedItem リスト
        """
        base_url: str = self._config.get("url", "")
        if not base_url:
            logger.error("source_id=%s: url が設定されていません", self._source_id)
            return []

        extraction = self._config.get("extraction", {})
        selectors = extraction.get("selectors", {})
        wait_for: str = extraction.get("wait_for", "domcontentloaded")

        article_sel: str = selectors.get("article_container", "article")
        title_sel: str = selectors.get("title", "h3 a, h4 a")
        url_sel: str = selectors.get("url", "a[href]")
        summary_sel: str = selectors.get("summary", "")
        source_sel: str = selectors.get("source", "")

        fetched_at = self.now_utc()
        items: list[FetchedItem] = []

        # browser コンテナへの CDP 接続 URL（docker-compose 内は http://browser:9222）
        browser_url = os.environ.get("BROWSER_REMOTE_URL", "http://localhost:9222")

        try:
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(browser_url)
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    locale="ja-JP",
                )
                page = await context.new_page()

                await page.goto(base_url, wait_until=wait_for, timeout=30000)

                articles: list[ElementHandle] = await page.query_selector_all(article_sel)
                logger.debug(
                    "%s: %d article 要素取得",
                    self._source_id,
                    len(articles),
                )

                for article in articles[:max_items]:
                    item = await self._parse_article(
                        article=article,
                        title_sel=title_sel,
                        url_sel=url_sel,
                        summary_sel=summary_sel,
                        source_sel=source_sel,
                        base_url=base_url,
                        fetched_at=fetched_at,
                    )
                    if item is not None:
                        items.append(item)

                await context.close()
                # browser.close() は呼ばない（共有リモートブラウザのため）

        except Exception as exc:
            logger.error("%s 取得エラー: %s", self._source_id, exc)
            return []

        logger.info("%s 取得完了: %d 件", self._source_id, len(items))
        return items

    async def _parse_article(
        self,
        article: ElementHandle,
        title_sel: str,
        url_sel: str,
        summary_sel: str,
        source_sel: str,
        base_url: str,
        fetched_at: Any,
    ) -> FetchedItem | None:
        """
        article 要素を FetchedItem に変換する。

        Args:
            article: Playwright の ElementHandle
            title_sel: タイトル要素の CSS セレクタ
            url_sel: URL 要素の CSS セレクタ
            summary_sel: サマリー要素の CSS セレクタ（省略可）
            source_sel: 出典名要素の CSS セレクタ（省略可）
            base_url: ベース URL（相対 URL 解決用）
            fetched_at: 取得時刻

        Returns:
            FetchedItem、またはパース失敗時 None
        """
        try:
            # タイトル取得
            title_el = await article.query_selector(title_sel)
            title = ""
            if title_el:
                title = _strip_html(await title_el.inner_text())

            if not title:
                return None

            # URL 取得
            url_el = await article.query_selector(url_sel)
            url = ""
            if url_el:
                href = await url_el.get_attribute("href")
                if href:
                    url = self._resolve_url(href, base_url)

            if not url:
                # URL なしはスキップ
                return None

            # サマリー取得（省略可）
            summary = ""
            if summary_sel:
                summary_el = await article.query_selector(summary_sel)
                if summary_el:
                    summary = _strip_html(await summary_el.inner_text())

            # 出典名取得（省略可）
            source_name = ""
            if source_sel:
                source_el = await article.query_selector(source_sel)
                if source_el:
                    source_name = _strip_html(await source_el.inner_text())

            return FetchedItem(
                title=title,
                url=url,
                content=summary,
                source_id=self._source_id,
                fetched_at=fetched_at,
                extra={"source_name": source_name} if source_name else {},
            )

        except Exception as exc:
            logger.warning("%s アイテムパースエラー: %s", self._source_id, exc)
            return None

    @staticmethod
    def _resolve_url(href: str, base_url: str) -> str:
        """
        相対 URL を絶対 URL に解決する。

        Args:
            href: リンクの href 属性値
            base_url: ベースとなるサイト URL

        Returns:
            絶対 URL 文字列
        """
        if href.startswith("http://") or href.startswith("https://"):
            return href

        # Google News の相対パス（./articles/... → https://news.google.com/articles/...）
        if href.startswith("./"):
            from urllib.parse import urljoin
            return urljoin(base_url, href)

        if href.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            return f"{parsed.scheme}://{parsed.netloc}{href}"

        return href
