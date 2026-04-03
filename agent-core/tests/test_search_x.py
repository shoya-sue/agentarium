"""
tests/test_search_x.py — SearchXSkill ユニットテスト

Playwright は MagicMock で差し替える（ネットワーク不要）。
"""

from __future__ import annotations

import sys
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ---------------------------------------------------------------------------
# クエリ組み立てテスト（_build_query）
# ---------------------------------------------------------------------------

class TestBuildQuery:
    """_build_query のクエリ文字列組み立てテスト"""

    def _build(self, **kwargs):
        from skills.perception.search_x import _build_query
        return _build_query(kwargs)

    def test_keyword_only(self):
        assert self._build(keyword="AI") == "AI"

    def test_lang(self):
        assert self._build(keyword="AI", lang="en") == "AI lang:en"

    def test_min_faves(self):
        q = self._build(keyword="AI", lang="en", min_faves=100)
        assert "min_faves:100" in q
        assert "lang:en" in q

    def test_since_until(self):
        q = self._build(keyword="AI", since="2026-01-01", until="2026-03-31")
        assert "since:2026-01-01" in q
        assert "until:2026-03-31" in q

    def test_filter_links(self):
        q = self._build(keyword="AI", filters=["links"])
        assert "filter:links" in q

    def test_exclude_replies(self):
        q = self._build(keyword="AI", exclude=["replies"])
        assert "-filter:replies" in q

    def test_multiple_filters_and_exclude(self):
        q = self._build(
            keyword="AI startup",
            lang="en",
            min_faves=200,
            filters=["links"],
            exclude=["replies", "retweets"],
            since="2026-01-01",
        )
        assert "AI startup" in q
        assert "lang:en" in q
        assert "min_faves:200" in q
        assert "filter:links" in q
        assert "-filter:replies" in q
        assert "-filter:retweets" in q
        assert "since:2026-01-01" in q

    def test_from_user_strips_at(self):
        q = self._build(keyword="", from_user="@elonmusk")
        assert "from:elonmusk" in q
        assert "from:@elonmusk" not in q

    def test_to_user(self):
        q = self._build(keyword="", to_user="elonmusk")
        assert "to:elonmusk" in q

    def test_exact_phrase(self):
        q = self._build(exact_phrase="large language model")
        assert '"large language model"' in q

    def test_or_keywords(self):
        q = self._build(keyword="", or_keywords=["AI", "LLM"])
        assert "AI OR LLM" in q

    def test_min_retweets_min_replies(self):
        q = self._build(keyword="X", min_retweets=50, min_replies=10)
        assert "min_retweets:50" in q
        assert "min_replies:10" in q

    def test_empty_params(self):
        q = self._build()
        assert q == ""

    def test_filter_verified(self):
        q = self._build(keyword="AI", filters=["verified"])
        assert "filter:verified" in q


# ---------------------------------------------------------------------------
# SearchXSkill.run() テスト
# ---------------------------------------------------------------------------

class TestSearchXSkillRun:
    """SearchXSkill.run() の統合テスト（Playwright モック）"""

    def _make_skill(self, tmp_path: Path):
        from skills.perception.search_x import SearchXSkill
        return SearchXSkill(data_dir=tmp_path)

    def _make_cookie_file(self, tmp_path: Path) -> Path:
        profile_dir = tmp_path / "browser-profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        cookies = [{"name": "auth_token", "value": "dummy", "domain": ".x.com", "path": "/"}]
        cookie_file = profile_dir / "cookies.json"
        cookie_file.write_text(json.dumps(cookies))
        return cookie_file

    def _make_mock_tweet_element(
        self,
        text="Test tweet",
        username="testuser",
        display_name="Test User",
        tweet_url="/testuser/status/123",
        faves=1000,
        retweets=100,
        replies=50,
        created_at="2026-01-01T00:00:00.000Z",
    ):
        """ツイート要素の MagicMock を生成する"""
        el = MagicMock()

        # tweetText
        text_el = AsyncMock()
        text_el.inner_text = AsyncMock(return_value=text)

        # User-Name
        user_el = AsyncMock()
        user_el.inner_text = AsyncMock(return_value=f"{display_name}\n@{username}")

        # time 要素
        time_el = AsyncMock()
        time_el.get_attribute = AsyncMock(return_value=created_at)
        parent_a = AsyncMock()
        parent_a.get_attribute = AsyncMock(return_value=tweet_url)
        time_el.evaluate_handle = AsyncMock(return_value=parent_a)

        # メトリクス要素
        def make_metric_el(count):
            m = AsyncMock()
            m.get_attribute = AsyncMock(return_value=f"{count} likes")
            return m

        like_el = make_metric_el(faves)
        rt_el = make_metric_el(retweets)
        reply_el = make_metric_el(replies)

        async def query_selector(selector):
            mapping = {
                "[data-testid='tweetText']": text_el,
                "[data-testid='User-Name']": user_el,
                "time": time_el,
                "[data-testid='like']": like_el,
                "[data-testid='retweet']": rt_el,
                "[data-testid='reply']": reply_el,
            }
            return mapping.get(selector)

        el.query_selector = query_selector
        return el

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, tmp_path):
        """キーワードなしで空リストを返す"""
        skill = self._make_skill(tmp_path)
        result = await skill.run({})
        assert result["tweets"] == []
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_url_is_encoded(self, tmp_path):
        """クエリが URL エンコードされている"""
        skill = self._make_skill(tmp_path)
        result_url = ""

        async def mock_fetch(url, cookies, max_results):
            nonlocal result_url
            result_url = url
            return []

        skill._fetch_tweets = mock_fetch
        await skill.run({"keyword": "AI startup", "lang": "en", "min_faves": 100})
        assert "AI" in result_url
        assert "lang%3Aen" in result_url or "lang:en" in result_url

    @pytest.mark.asyncio
    async def test_sort_top_default(self, tmp_path):
        """デフォルトのソートは top"""
        skill = self._make_skill(tmp_path)
        captured_url = []

        async def mock_fetch(url, cookies, max_results):
            captured_url.append(url)
            return []

        skill._fetch_tweets = mock_fetch
        await skill.run({"keyword": "AI"})
        assert "f=top" in captured_url[0]

    @pytest.mark.asyncio
    async def test_sort_live(self, tmp_path):
        """sort=live のとき f=live が URL に含まれる"""
        skill = self._make_skill(tmp_path)
        captured_url = []

        async def mock_fetch(url, cookies, max_results):
            captured_url.append(url)
            return []

        skill._fetch_tweets = mock_fetch
        await skill.run({"keyword": "AI", "sort": "live"})
        assert "f=live" in captured_url[0]

    @pytest.mark.asyncio
    async def test_returns_tweet_data(self, tmp_path):
        """ツイートデータが正しく返される"""
        skill = self._make_skill(tmp_path)

        mock_tweets = [
            {
                "text": "AI is amazing",
                "author": "user1",
                "display_name": "User One",
                "url": "https://x.com/user1/status/1",
                "faves": 500,
                "retweets": 50,
                "replies": 20,
                "created_at": "2026-01-15T10:00:00.000Z",
            }
        ]

        async def mock_fetch(url, cookies, max_results):
            return mock_tweets

        skill._fetch_tweets = mock_fetch
        result = await skill.run({"keyword": "AI", "min_faves": 100})

        assert result["count"] == 1
        assert result["tweets"][0]["text"] == "AI is amazing"
        assert result["tweets"][0]["faves"] == 500
        assert result["query"] == "AI min_faves:100"

    @pytest.mark.asyncio
    async def test_fetch_error_returns_empty(self, tmp_path):
        """_fetch_tweets がエラーを投げても空リストを返す"""
        skill = self._make_skill(tmp_path)

        async def mock_fetch(url, cookies, max_results):
            raise RuntimeError("ネットワークエラー")

        skill._fetch_tweets = mock_fetch
        result = await skill.run({"keyword": "AI"})

        assert result["tweets"] == []
        assert result["count"] == 0
        assert "error" in result

    @pytest.mark.asyncio
    async def test_cookie_file_loaded(self, tmp_path):
        """Cookie ファイルが正常に読み込まれる"""
        cookie_file = self._make_cookie_file(tmp_path)
        skill = self._make_skill(tmp_path)

        captured_cookies = []

        async def mock_fetch(url, cookies, max_results):
            captured_cookies.extend(cookies)
            return []

        skill._fetch_tweets = mock_fetch
        await skill.run({"keyword": "AI", "cookies_file": str(cookie_file)})

        assert len(captured_cookies) == 1
        assert captured_cookies[0]["name"] == "auth_token"

    @pytest.mark.asyncio
    async def test_max_results_passed_to_fetch(self, tmp_path):
        """max_results が _fetch_tweets に渡される"""
        skill = self._make_skill(tmp_path)
        captured = {}

        async def mock_fetch(url, cookies, max_results):
            captured["max_results"] = max_results
            return []

        skill._fetch_tweets = mock_fetch
        await skill.run({"keyword": "AI", "max_results": 5})
        assert captured["max_results"] == 5


# ---------------------------------------------------------------------------
# _extract_tweet テスト
# ---------------------------------------------------------------------------

class TestExtractTweet:
    """_extract_tweet の DOM 解析テスト"""

    @pytest.mark.asyncio
    async def test_extract_tweet_fields(self):
        """ツイート要素から全フィールドが取得できる"""
        from skills.perception.search_x import SearchXSkill
        skill = SearchXSkill()

        runner = TestSearchXSkillRun()
        el = runner._make_mock_tweet_element(
            text="Hello world",
            username="hello_user",
            display_name="Hello User",
            tweet_url="/hello_user/status/999",
            faves=1234,
            retweets=56,
            replies=7,
            created_at="2026-03-01T12:00:00.000Z",
        )

        result = await skill._extract_tweet(el)

        assert result is not None
        assert result["text"] == "Hello world"
        assert result["author"] == "hello_user"
        assert result["display_name"] == "Hello User"
        assert result["url"] == "https://x.com/hello_user/status/999"
        assert result["faves"] == 1234
        assert result["retweets"] == 56
        assert result["replies"] == 7
        assert result["created_at"] == "2026-03-01T12:00:00.000Z"

    @pytest.mark.asyncio
    async def test_empty_text_returns_none(self):
        """本文なしのツイートは None を返す"""
        from skills.perception.search_x import SearchXSkill
        skill = SearchXSkill()

        runner = TestSearchXSkillRun()
        el = runner._make_mock_tweet_element(text="")
        result = await skill._extract_tweet(el)
        assert result is None


# ---------------------------------------------------------------------------
# _extract_metric テスト
# ---------------------------------------------------------------------------

class TestExtractMetric:
    """_extract_metric の数値抽出テスト"""

    @pytest.mark.asyncio
    async def test_extracts_number_from_aria_label(self):
        from skills.perception.search_x import SearchXSkill
        skill = SearchXSkill()

        tweet_el = MagicMock()
        metric_el = AsyncMock()
        metric_el.get_attribute = AsyncMock(return_value="1234 likes")
        tweet_el.query_selector = AsyncMock(return_value=metric_el)

        result = await skill._extract_metric(tweet_el, "[data-testid='like']")
        assert result == 1234

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_element(self):
        from skills.perception.search_x import SearchXSkill
        skill = SearchXSkill()

        tweet_el = MagicMock()
        tweet_el.query_selector = AsyncMock(return_value=None)

        result = await skill._extract_metric(tweet_el, "[data-testid='like']")
        assert result == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_aria_label(self):
        from skills.perception.search_x import SearchXSkill
        skill = SearchXSkill()

        tweet_el = MagicMock()
        metric_el = AsyncMock()
        metric_el.get_attribute = AsyncMock(return_value=None)
        tweet_el.query_selector = AsyncMock(return_value=metric_el)

        result = await skill._extract_metric(tweet_el, "[data-testid='like']")
        assert result == 0
