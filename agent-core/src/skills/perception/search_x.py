"""
skills/perception/search_x.py — X (Twitter) 検索 Skill

高度な検索クエリを組み立てて x.com/search にアクセスし、
ツイートを DOM から取得して返す。

対応フィルタ:
  - keyword, lang, min_faves, min_retweets, min_replies
  - since / until（日付指定）
  - filters: ["links", "media", "images", "videos"]
  - exclude: ["replies", "retweets"]
  - from_user, to_user
  - exact_phrase

Skill 入出力スキーマ: config/skills/perception/search_x.yaml
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 検索結果ページ URL テンプレート
# f=top: エンゲージメント順（バズツイート取得に適する）
# f=live: 時系列順
_SEARCH_URL_TEMPLATE = "https://x.com/search?q={query}&f={sort}&src=typed_query"

# DOM セレクタ（Phase 0 V5 実測値 / X の data-testid ベース）
_TWEET_SELECTOR = "[data-testid='tweet']"
_TWEET_TEXT_SELECTOR = "[data-testid='tweetText']"
_USER_NAME_SELECTOR = "[data-testid='User-Name']"
_LIKE_SELECTOR = "[data-testid='like']"
_RETWEET_SELECTOR = "[data-testid='retweet']"
_REPLY_SELECTOR = "[data-testid='reply']"

# ページ読み込み待機のタイムアウト（ms）
_PAGE_TIMEOUT_MS = 30000
# ツイート要素の出現待機タイムアウト（ms）
_TWEET_WAIT_MS = 15000
# スクロール後の追加読み込み待機（ms）
_SCROLL_WAIT_MS = 2000

# デフォルト最大取得件数
_DEFAULT_MAX_RESULTS = 20


def _build_query(params: dict[str, Any]) -> str:
    """
    パラメータから X の高度検索クエリ文字列を組み立てる。

    Examples:
        keyword="AI", lang="en", min_faves=100, filters=["links"], exclude=["replies"]
        → 'AI lang:en min_faves:100 filter:links -filter:replies'
    """
    parts: list[str] = []

    # キーワード（完全一致フレーズはダブルクォートで囲む）
    keyword: str = params.get("keyword", "").strip()
    exact_phrase: str = params.get("exact_phrase", "").strip()
    if exact_phrase:
        parts.append(f'"{exact_phrase}"')
    if keyword:
        parts.append(keyword)

    # OR 検索
    or_keywords: list[str] = params.get("or_keywords", [])
    if or_keywords:
        parts.append(" OR ".join(or_keywords))

    # 言語
    lang: str | None = params.get("lang")
    if lang:
        parts.append(f"lang:{lang}")

    # ユーザー指定
    from_user: str | None = params.get("from_user")
    if from_user:
        parts.append(f"from:{from_user.lstrip('@')}")

    to_user: str | None = params.get("to_user")
    if to_user:
        parts.append(f"to:{to_user.lstrip('@')}")

    # 日付範囲
    since: str | None = params.get("since")
    if since:
        parts.append(f"since:{since}")

    until: str | None = params.get("until")
    if until:
        parts.append(f"until:{until}")

    # エンゲージメント閾値
    min_faves: int | None = params.get("min_faves")
    if min_faves:
        parts.append(f"min_faves:{min_faves}")

    min_retweets: int | None = params.get("min_retweets")
    if min_retweets:
        parts.append(f"min_retweets:{min_retweets}")

    min_replies: int | None = params.get("min_replies")
    if min_replies:
        parts.append(f"min_replies:{min_replies}")

    # コンテンツフィルタ（links / media / images / videos / verified）
    filters: list[str] = params.get("filters", [])
    for f in filters:
        parts.append(f"filter:{f}")

    # 除外フィルタ（replies / retweets）
    exclude: list[str] = params.get("exclude", [])
    for e in exclude:
        parts.append(f"-filter:{e}")

    return " ".join(parts)


class SearchXSkill:
    """
    search_x Skill の実装。

    高度な検索クエリで x.com/search にアクセスし、
    ツイートを DOM から解析して返す。
    """

    def __init__(self, data_dir: Path | str | None = None) -> None:
        if data_dir is None:
            data_dir = Path(__file__).parent.parent.parent.parent.parent.parent / "data"
        self._data_dir = Path(data_dir)

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        X を検索してツイート一覧を返す。

        Args:
            params:
                keyword (str): 検索キーワード
                exact_phrase (str | None): 完全一致フレーズ
                or_keywords (list[str] | None): OR 検索キーワード
                lang (str | None): 言語コード（例: "en", "ja"）
                from_user (str | None): 特定ユーザーのツイートのみ
                to_user (str | None): 特定ユーザーへのリプライのみ
                since (str | None): 開始日（YYYY-MM-DD）
                until (str | None): 終了日（YYYY-MM-DD）
                min_faves (int | None): 最小いいね数
                min_retweets (int | None): 最小リポスト数
                min_replies (int | None): 最小リプライ数
                filters (list[str] | None): 追加フィルタ（"links"/"media"/"images"/"videos"/"verified"）
                exclude (list[str] | None): 除外フィルタ（"replies"/"retweets"）
                sort (str | None): "top"（エンゲージメント順）または "live"（時系列順）デフォルト: "top"
                max_results (int | None): 最大取得件数（デフォルト: 20）
                cookies_file (str | None): Cookie ファイルパス

        Returns:
            {
                "tweets": list[dict],  # ツイートリスト
                "query": str,          # 実際に使用した検索クエリ
                "url": str,            # アクセスした URL
                "count": int,          # 取得件数
                "fetched_at": str,     # 取得日時（ISO 8601）
            }

            各 tweet:
            {
                "text": str,           # ツイート本文
                "author": str,         # ユーザー名（@なし）
                "display_name": str,   # 表示名
                "url": str,            # ツイート URL
                "faves": int,          # いいね数
                "retweets": int,       # リポスト数
                "replies": int,        # リプライ数
                "created_at": str,     # 投稿日時（ISO 8601）
            }
        """
        query = _build_query(params)
        sort: str = params.get("sort", "top")
        max_results: int = int(params.get("max_results") or _DEFAULT_MAX_RESULTS)
        cookies_file_str: str | None = params.get("cookies_file")
        fetched_at = datetime.now(timezone.utc).isoformat()

        if not query.strip():
            logger.warning("search_x: 検索クエリが空です")
            return {
                "tweets": [],
                "query": "",
                "url": "",
                "count": 0,
                "fetched_at": fetched_at,
            }

        encoded_query = urllib.parse.quote(query)
        url = _SEARCH_URL_TEMPLATE.format(query=encoded_query, sort=sort)

        logger.info("search_x: query='%s' sort=%s max=%d", query, sort, max_results)

        cookies_file = Path(
            cookies_file_str or str(self._data_dir / "browser-profile" / "cookies.json")
        )

        # Cookie 読み込み
        cookies: list[dict[str, Any]] = []
        if cookies_file.exists():
            try:
                raw = json.loads(cookies_file.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    cookies = raw
                elif isinstance(raw, dict) and "cookies" in raw:
                    cookies = raw["cookies"]
                logger.debug("search_x: Cookie 読み込み %d 件", len(cookies))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("search_x: Cookie 読み込みエラー: %s", exc)
        else:
            logger.warning("search_x: Cookie ファイルなし: %s", cookies_file)

        try:
            tweets = await self._fetch_tweets(url, cookies, max_results)
            return {
                "tweets": tweets,
                "query": query,
                "url": url,
                "count": len(tweets),
                "fetched_at": fetched_at,
            }
        except Exception as exc:
            logger.error("search_x: 取得エラー: %s", exc)
            return {
                "tweets": [],
                "query": query,
                "url": url,
                "count": 0,
                "fetched_at": fetched_at,
                "error": str(exc),
            }

    async def _fetch_tweets(
        self,
        url: str,
        cookies: list[dict[str, Any]],
        max_results: int,
    ) -> list[dict[str, Any]]:
        """
        Playwright を使って検索結果ページからツイートを取得する。

        テスト可能にするため、page 操作部分を _parse_tweets に分離。
        """
        try:
            from rebrowser_playwright.async_api import async_playwright as _playwright
        except ImportError:
            from playwright.async_api import async_playwright as _playwright

        async with _playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="ja-JP",
            )

            # Cookie 注入
            if cookies:
                valid_cookies = [
                    c for c in cookies
                    if c.get("domain") and (
                        "x.com" in c["domain"] or "twitter.com" in c["domain"]
                    )
                ]
                if valid_cookies:
                    await context.add_cookies(valid_cookies)

            page = await context.new_page()

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=_PAGE_TIMEOUT_MS)

                # ツイート要素が出現するまで待機
                try:
                    await page.wait_for_selector(_TWEET_SELECTOR, timeout=_TWEET_WAIT_MS)
                except Exception:
                    logger.warning("search_x: ツイート要素が見つかりません（結果なし or ログイン切れ）")
                    await browser.close()
                    return []

                # 必要件数になるまでスクロールして追加ロード
                tweets = await self._parse_tweets(page, max_results)

                if len(tweets) < max_results:
                    import asyncio
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(_SCROLL_WAIT_MS / 1000)
                    tweets = await self._parse_tweets(page, max_results)

            finally:
                await browser.close()

        logger.info("search_x: %d 件取得", len(tweets))
        return tweets

    async def _parse_tweets(
        self,
        page: Any,
        max_results: int,
    ) -> list[dict[str, Any]]:
        """
        ページ上のツイート要素を解析してリストを返す。

        テスト可能にするため page を引数として受け取る。
        """
        tweet_elements = await page.query_selector_all(_TWEET_SELECTOR)
        results: list[dict[str, Any]] = []

        for el in tweet_elements[:max_results]:
            try:
                tweet = await self._extract_tweet(el)
                if tweet:
                    results.append(tweet)
            except Exception as exc:
                logger.debug("search_x: ツイート解析エラー（スキップ）: %s", exc)

        return results

    async def _extract_tweet(self, el: Any) -> dict[str, Any] | None:
        """
        1つのツイート要素から必要なデータを抽出する。

        Returns:
            ツイートデータ dict、または取得失敗時 None
        """
        # 本文
        text_el = await el.query_selector(_TWEET_TEXT_SELECTOR)
        text: str = (await text_el.inner_text()).strip() if text_el else ""
        if not text:
            return None

        # ユーザー名・表示名
        # User-Name 要素は「表示名\n@username」の形式
        username = ""
        display_name = ""
        user_el = await el.query_selector(_USER_NAME_SELECTOR)
        if user_el:
            user_text = (await user_el.inner_text()).strip()
            lines = [line.strip() for line in user_text.splitlines() if line.strip()]
            if lines:
                display_name = lines[0]
            # @username を探す
            for line in lines:
                if line.startswith("@"):
                    username = line.lstrip("@")
                    break

        # ツイート URL（time 要素の親 a タグの href）
        tweet_url = ""
        time_el = await el.query_selector("time")
        if time_el:
            parent_a = await time_el.evaluate_handle("el => el.closest('a')")
            if parent_a:
                href = await parent_a.get_attribute("href")
                if href:
                    tweet_url = f"https://x.com{href}" if href.startswith("/") else href

        # 投稿日時
        created_at = ""
        if time_el:
            dt_attr = await time_el.get_attribute("datetime")
            if dt_attr:
                created_at = dt_attr

        # エンゲージメント数値（aria-label から数値を抽出）
        faves = await self._extract_metric(el, _LIKE_SELECTOR)
        retweets = await self._extract_metric(el, _RETWEET_SELECTOR)
        replies = await self._extract_metric(el, _REPLY_SELECTOR)

        return {
            "text": text,
            "author": username,
            "display_name": display_name,
            "url": tweet_url,
            "faves": faves,
            "retweets": retweets,
            "replies": replies,
            "created_at": created_at,
        }

    async def _extract_metric(self, tweet_el: Any, selector: str) -> int:
        """
        エンゲージメント数値を aria-label から取得する。

        aria-label 例: "1,234 件のいいね" / "1234 likes"
        """
        metric_el = await tweet_el.query_selector(selector)
        if not metric_el:
            return 0
        aria = await metric_el.get_attribute("aria-label") or ""
        # 数値部分を抽出（カンマ区切り・K/M 表記は考慮しない）
        import re
        match = re.search(r"([\d,]+)", aria.replace(",", "").replace(".", ""))
        if match:
            try:
                return int(match.group(1).replace(",", ""))
            except ValueError:
                pass
        return 0
