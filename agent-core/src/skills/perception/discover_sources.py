"""
skills/perception/discover_sources.py — RSS ソース自律発見 Skill

キャラクターの興味・関心キーワードから DuckDuckGo で検索し、
新しい RSS フィード URL を発見して config/sources/rss_feeds.yaml に追加する。

フロー:
  1. interests（話題リスト）ごとに DuckDuckGo HTML 検索
  2. 検索結果ドメインのホームページから RSS フィードを検出（<link> タグ + common paths）
  3. feedparser で有効性を検証（最低 1 エントリ必要）
  4. 既存 rss_feeds.yaml と重複チェック
  5. rss_feeds.yaml に追記（rate_limit: セクションの直前に挿入）

Skill 入出力スキーマ: config/skills/perception/discover_sources.yaml
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from pathlib import Path
from typing import Any

import feedparser
import httpx
import yaml
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# DuckDuckGo HTML 検索エンドポイント（API キー不要）
_DDG_URL = "https://html.duckduckgo.com/html/"

# HTTP タイムアウト（秒）
_HTTP_TIMEOUT = 15.0

# 1 クエリから取得するドメイン候補数の上限
_MAX_DOMAINS_PER_QUERY = 5

# ホームページで <link> タグが見つからない場合に試行する RSS パス候補
_RSS_CANDIDATE_PATHS = (
    "/feed",
    "/feed.xml",
    "/rss",
    "/rss.xml",
    "/atom.xml",
    "/feed/rss",
    "/index.rss",
    "/feeds/posts/default",  # Blogger
)

# インタレストキーワード → カテゴリ マッピング（部分一致、小文字）
_CATEGORY_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("anime", "entertainment"),
    ("アニメ", "entertainment"),
    ("manga", "entertainment"),
    ("マンガ", "entertainment"),
    ("comic", "entertainment"),
    ("game", "entertainment"),
    ("ゲーム", "entertainment"),
    ("gaming", "entertainment"),
    ("steam", "entertainment"),
    ("music", "entertainment"),
    ("音楽", "entertainment"),
    ("film", "entertainment"),
    ("movie", "entertainment"),
    ("映画", "entertainment"),
    ("tech", "tech"),
    ("technology", "tech"),
    ("programming", "tech"),
    ("software", "tech"),
    ("開発", "tech"),
    ("プログラミング", "tech"),
    ("ai", "tech"),
    ("llm", "tech"),
    ("ml", "tech"),
    ("oss", "tech"),
    ("news", "news"),
    ("ニュース", "news"),
)


def _infer_category(interest: str) -> str:
    """インタレスト文字列からカテゴリを推定する。"""
    lower = interest.lower()
    for keyword, category in _CATEGORY_KEYWORDS:
        if keyword.lower() in lower:
            return category
    return "tech"


def _has_japanese(text: str) -> bool:
    """テキストに日本語（ひらがな・カタカナ・漢字）が含まれるか判定する。"""
    return bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", text))


async def _search_ddg(query: str, client: httpx.AsyncClient) -> list[str]:
    """
    DuckDuckGo HTML 検索からドメイン URL リストを返す。

    DDG はリンクを /l/?uddg=URL_ENCODED 形式で返す。
    uddg パラメータをデコードして実際のドメインを抽出する。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    }
    try:
        resp = await client.post(
            _DDG_URL,
            data={"q": f"{query} RSS フィード", "kl": "jp-ja"},
            headers=headers,
            follow_redirects=True,
        )
    except httpx.RequestError as exc:
        logger.warning("discover_sources: DDG 検索エラー query=%r error=%s", query, exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    domains: list[str] = []

    for a in soup.select("a.result__a"):
        href = a.get("href", "")
        actual_url = ""

        if "uddg=" in href:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            uddg_list = qs.get("uddg", [])
            if uddg_list:
                actual_url = urllib.parse.unquote(uddg_list[0])
        elif href.startswith("http"):
            actual_url = href

        if not actual_url:
            continue

        parsed = urllib.parse.urlparse(actual_url)
        if not parsed.scheme or not parsed.netloc:
            continue

        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in domains:
            domains.append(base)

        if len(domains) >= _MAX_DOMAINS_PER_QUERY:
            break

    logger.debug("discover_sources: DDG query=%r → %d domains", query, len(domains))
    return domains


async def _find_rss_from_domain(base_url: str, client: httpx.AsyncClient) -> list[str]:
    """
    ドメインのホームページから RSS/Atom フィード URL を検出する。

    1. ホームページの <link rel="alternate" type="application/rss+xml"> を確認
    2. 見つからない場合は _RSS_CANDIDATE_PATHS を HEAD リクエストで試行
    """
    feed_urls: list[str] = []

    # 1. ホームページの <link> タグから検出
    try:
        resp = await client.get(base_url, follow_redirects=True)
        soup = BeautifulSoup(resp.text, "html.parser")
        for link in soup.find_all("link", rel="alternate"):
            link_type = link.get("type", "")
            if "rss" in link_type or "atom" in link_type:
                href = link.get("href", "")
                if href:
                    full = urllib.parse.urljoin(str(resp.url), href)
                    if full not in feed_urls:
                        feed_urls.append(full)
    except (httpx.RequestError, httpx.HTTPStatusError):
        pass

    # 2. <link> で見つからない場合は共通パスを試行
    if not feed_urls:
        for path in _RSS_CANDIDATE_PATHS:
            url = base_url.rstrip("/") + path
            try:
                head_resp = await client.head(url, follow_redirects=True)
                if head_resp.status_code == 200:
                    feed_urls.append(url)
                    break  # 1 つ見つかればOK
            except (httpx.RequestError, httpx.HTTPStatusError):
                continue

    return feed_urls


async def _validate_feed(url: str, client: httpx.AsyncClient) -> dict[str, Any] | None:
    """
    feedparser でフィードの有効性を確認し、メタデータを返す。

    Returns:
        {"url": str, "title": str, "language": str} または None（無効な場合）
    """
    try:
        resp = await client.get(url, follow_redirects=True)
        if resp.status_code != 200:
            return None
        content = resp.text
    except (httpx.RequestError, httpx.HTTPStatusError):
        return None

    parsed = feedparser.parse(content)
    # bozo=True でかつエントリが 0 件は無効
    if parsed.bozo and not parsed.entries:
        return None
    if not parsed.entries:
        return None

    title = parsed.feed.get("title", "")
    lang_hint = parsed.feed.get("language", "")
    # タイトルに日本語 or language フィールドが ja で始まる場合は日本語
    language = "ja" if (_has_japanese(title) or lang_hint.startswith("ja")) else "en"

    return {
        "url": url,
        "title": title,
        "language": language,
    }


def _load_existing_urls(rss_yaml_path: Path) -> set[str]:
    """既存 rss_feeds.yaml からフィード URL のセットを返す。"""
    if not rss_yaml_path.exists():
        return set()
    with rss_yaml_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    feeds = data.get("feeds", [])
    return {f.get("url", "") for f in feeds if isinstance(f, dict)}


def _append_feeds_to_yaml(rss_yaml_path: Path, feeds: list[dict[str, Any]]) -> None:
    """
    rss_feeds.yaml の feeds セクション末尾に新しいフィードを挿入する。

    pyyaml ではコメントが失われるため、テキスト挿入方式を使用する。
    "rate_limit:" 行の直前に挿入し、既存の構造・コメントを保持する。
    """
    lines: list[str] = []
    for feed in feeds:
        lines.append(f'\n  - url: "{feed["url"]}"')
        lines.append(f'    category: {feed["category"]}')
        lines.append(f'    language: {feed["language"]}')
        if feed.get("title"):
            # タイトルをインラインコメントとして付加（50 文字上限）
            title_comment = feed["title"][:50].replace("\n", " ")
            lines.append(f"    # {title_comment}")

    with rss_yaml_path.open("r", encoding="utf-8") as f:
        content = f.read()

    insertion_marker = "\nrate_limit:"
    if insertion_marker in content:
        insert_at = content.index(insertion_marker)
        new_content = content[:insert_at] + "\n".join(lines) + "\n" + content[insert_at:]
    else:
        # フォールバック: ファイル末尾に追記
        new_content = content + "\n".join(lines) + "\n"

    with rss_yaml_path.open("w", encoding="utf-8") as f:
        f.write(new_content)


class DiscoverSourcesSkill:
    """
    discover_sources Skill の実装。

    DuckDuckGo HTML 検索 → RSS URL 検出 → feedparser 検証 → rss_feeds.yaml 追記
    という流れで新しい情報源を自律的に発見する。
    """

    def __init__(self, config_dir: Path | str | None = None) -> None:
        if config_dir is None:
            config_dir = Path(__file__).parent.parent.parent.parent.parent / "config"
        self._config_dir = Path(config_dir)
        self._rss_yaml = self._config_dir / "sources" / "rss_feeds.yaml"

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        新しい RSS ソースを発見して rss_feeds.yaml に追加する。

        Args:
            params:
                interests (list[str]): 検索するトピック
                    例: ["アニメ", "インディーゲーム", "AI・LLM"]
                max_new_feeds (int): 追加する最大フィード数（デフォルト 3）
                dry_run (bool): True の場合、YAML への書き込みをスキップ（デフォルト False）

        Returns:
            {
                "added": list[dict],      # 実際に追加されたフィード（dry_run=True の場合は空）
                "discovered": list[dict], # 発見されたフィード全件（dry_run 時も含む）
                "skipped_existing": int,  # 既存フィードと重複してスキップした数
                "skipped_invalid": int,   # feedparser 検証失敗でスキップした数
                "dry_run": bool,
            }
        """
        interests: list[str] = params.get("interests", [])
        max_new_feeds: int = int(params.get("max_new_feeds", 3))
        dry_run: bool = bool(params.get("dry_run", False))

        if not interests:
            logger.warning("discover_sources: interests が空のため終了")
            return {
                "added": [],
                "discovered": [],
                "skipped_existing": 0,
                "skipped_invalid": 0,
                "dry_run": dry_run,
            }

        existing_urls = _load_existing_urls(self._rss_yaml)
        discovered: list[dict[str, Any]] = []
        skipped_existing = 0
        skipped_invalid = 0

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            for interest in interests:
                if len(discovered) >= max_new_feeds:
                    break

                category = _infer_category(interest)
                domains = await _search_ddg(interest, client)

                for domain in domains:
                    if len(discovered) >= max_new_feeds:
                        break

                    feed_urls = await _find_rss_from_domain(domain, client)

                    for feed_url in feed_urls:
                        if feed_url in existing_urls:
                            skipped_existing += 1
                            logger.debug("discover_sources: 重複スキップ url=%s", feed_url)
                            continue

                        meta = await _validate_feed(feed_url, client)
                        if meta is None:
                            skipped_invalid += 1
                            logger.debug("discover_sources: 無効スキップ url=%s", feed_url)
                            continue

                        entry: dict[str, Any] = {
                            "url": feed_url,
                            "title": meta["title"],
                            "language": meta["language"],
                            "category": category,
                        }
                        discovered.append(entry)
                        # 同一セッション内の重複を防ぐため即時追加
                        existing_urls.add(feed_url)
                        logger.info(
                            "discover_sources: 新しいフィードを発見 url=%s title=%r category=%s",
                            feed_url,
                            meta["title"],
                            category,
                        )
                        break  # 1 ドメインから 1 フィードのみ

        if discovered and not dry_run:
            _append_feeds_to_yaml(self._rss_yaml, discovered)
            logger.info(
                "discover_sources: %d 件を rss_feeds.yaml に追加: %s",
                len(discovered),
                [f["url"] for f in discovered],
            )
        elif discovered and dry_run:
            logger.info(
                "discover_sources: dry_run=True — %d 件発見（書き込みスキップ）: %s",
                len(discovered),
                [f["url"] for f in discovered],
            )

        return {
            "added": discovered if not dry_run else [],
            "discovered": discovered,
            "skipped_existing": skipped_existing,
            "skipped_invalid": skipped_invalid,
            "dry_run": dry_run,
        }
