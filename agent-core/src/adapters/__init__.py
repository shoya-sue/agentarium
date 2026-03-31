"""ソースアダプタパッケージ"""
from .base import BaseAdapter, FetchedItem
from .hn_api import HackerNewsAdapter
from .rss import RSSAdapter
from .github_trending import GitHubTrendingAdapter

__all__ = [
    "BaseAdapter",
    "FetchedItem",
    "HackerNewsAdapter",
    "RSSAdapter",
    "GitHubTrendingAdapter",
]
