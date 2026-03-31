"""
V4: ソースアダプタ疎通検証
  - Hacker News API（公開 JSON API）
  - RSS フィード（hnrss.org）
  - GitHub Trending（HTML パース）
合格基準:
  - HTTP 200 + 正常パース
"""

import json
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional, Tuple

TIMEOUT = 15


@dataclass
class SourceResult:
    name: str
    ok: bool
    status_code: Optional[int]
    item_count: int
    latency_ms: float
    error: str = ""


def fetch(url: str) -> Tuple[int, bytes, float]:
    """(status_code, body, latency_ms)"""
    t0 = time.perf_counter()
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read()
            latency_ms = (time.perf_counter() - t0) * 1000
            return resp.status, body, latency_ms
    except urllib.error.HTTPError as e:
        latency_ms = (time.perf_counter() - t0) * 1000
        return e.code, b"", latency_ms


def test_hacker_news_api() -> SourceResult:
    """HN Firebase API: トップストーリー ID リストを取得"""
    url = "https://hacker-news.firebaseio.com/v0/topstories.json"
    print(f"  GET {url}")
    try:
        status, body, ms = fetch(url)
        if status == 200:
            ids = json.loads(body)
            count = len(ids) if isinstance(ids, list) else 0
            print(f"  → {status} / {count} stories / {ms:.0f}ms")
            return SourceResult("hacker_news_api", count > 0, status, count, ms)
        else:
            print(f"  → {status} FAIL")
            return SourceResult("hacker_news_api", False, status, 0, ms)
    except Exception as e:
        print(f"  → ERROR: {e}")
        return SourceResult("hacker_news_api", False, None, 0, 0.0, str(e))


def test_hn_rss() -> SourceResult:
    """HN RSS フィード: XML パース検証"""
    url = "https://hnrss.org/frontpage"
    print(f"  GET {url}")
    try:
        status, body, ms = fetch(url)
        if status == 200:
            root = ET.fromstring(body)
            # RSS 2.0: <rss><channel><item>...</item>
            items = root.findall(".//item")
            count = len(items)
            first_title = items[0].findtext("title", "") if items else ""
            print(f"  → {status} / {count} items / {ms:.0f}ms / first: '{first_title[:50]}'")
            return SourceResult("hn_rss", count > 0, status, count, ms)
        else:
            print(f"  → {status} FAIL")
            return SourceResult("hn_rss", False, status, 0, ms)
    except Exception as e:
        print(f"  → ERROR: {e}")
        return SourceResult("hn_rss", False, None, 0, 0.0, str(e))


def test_github_trending_html() -> SourceResult:
    """GitHub Trending: HTML に article.Box-row が存在するか確認"""
    url = "https://github.com/trending"
    print(f"  GET {url}")
    try:
        status, body, ms = fetch(url)
        if status == 200:
            html = body.decode("utf-8", errors="replace")
            # article タグの数を大雑把にカウント（lxml なし）
            count = html.count("<article")
            selector_ok = 'Box-row' in html or 'trending' in html.lower()
            print(f"  → {status} / article要素: {count}件 / {ms:.0f}ms")
            return SourceResult("github_trending", selector_ok and count > 0, status, count, ms)
        else:
            print(f"  → {status} FAIL")
            return SourceResult("github_trending", False, status, 0, ms)
    except Exception as e:
        print(f"  → ERROR: {e}")
        return SourceResult("github_trending", False, None, 0, 0.0, str(e))


def test_rss_feed(name: str, url: str) -> SourceResult:
    """汎用 RSS/Atom フィード疎通テスト"""
    print(f"  GET {url}")
    try:
        status, body, ms = fetch(url)
        if status == 200:
            root = ET.fromstring(body)
            # RSS 2.0
            items = root.findall(".//item")
            # Atom
            if not items:
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                items = root.findall(".//atom:entry", ns)
                if not items:
                    items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
            count = len(items)
            print(f"  → {status} / {count} items / {ms:.0f}ms")
            return SourceResult(name, count > 0, status, count, ms)
        else:
            print(f"  → {status} FAIL")
            return SourceResult(name, False, status, 0, ms)
    except Exception as e:
        print(f"  → ERROR: {e}")
        return SourceResult(name, False, None, 0, 0.0, str(e))


def main() -> None:
    print("=" * 60)
    print("V4: ソースアダプタ疎通")
    print("=" * 60)

    results: list[SourceResult] = []

    print("\n--- Hacker News API ---")
    results.append(test_hacker_news_api())

    print("\n--- HN RSS フィード ---")
    results.append(test_hn_rss())

    print("\n--- GitHub Trending ---")
    results.append(test_github_trending_html())

    print("\n--- 追加 RSS フィード ---")
    # config/sources/rss_feeds.yaml に定義済みのフィードから代表例
    rss_feeds = [
        ("techcrunch", "https://techcrunch.com/feed/"),
        ("wired_ai", "https://www.wired.com/feed/tag/artificial-intelligence/latest/rss"),
    ]
    for name, url in rss_feeds:
        results.append(test_rss_feed(name, url))

    # 判定
    print("\n--- 判定 ---")
    ok_count = sum(1 for r in results if r.ok)
    print(f"  合格: {ok_count}/{len(results)}")
    for r in results:
        status = "OK" if r.ok else "FAIL"
        error_info = f" ({r.error})" if r.error else ""
        print(f"  [{status}] {r.name}: {r.item_count}件{error_info}")

    core_sources_ok = all(
        r.ok for r in results if r.name in {"hacker_news_api", "hn_rss"}
    )
    if core_sources_ok:
        print("\n合格: コアソース（HN API / RSS）が正常動作しています。")
    else:
        print("\n注意: コアソースに問題あり。ネットワーク接続を確認してください。")


if __name__ == "__main__":
    main()
