"""
skills/perception/browse_source.py — ソース情報収集 Skill

config/sources/{source_id}.yaml の type フィールドに応じてアダプタを選択する。

type: api          → HackerNewsAdapter
type: rss          → RSSAdapter
type: browser      → GitHubTrendingAdapter
type: browser_stealth → (Phase 1 では未使用、X は Phase 1 読み取り専用で保留)

Skill の入力/出力スキーマは config/skills/perception/browse_source.yaml で定義。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from adapters import (
    BaseAdapter,
    FetchedItem,
    HackerNewsAdapter,
    RSSAdapter,
    GitHubTrendingAdapter,
)
from utils.config import load_yaml_config

logger = logging.getLogger(__name__)


# source type → アダプタクラス のマッピング
_ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    "api": HackerNewsAdapter,
    "rss": RSSAdapter,
    "browser": GitHubTrendingAdapter,
}


class BrowseSourceSkill:
    """
    browse_source Skill の実装。

    SkillEngine に登録されるハンドラクラス。
    インスタンスメソッド run() を SkillHandler として使用する。
    """

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir
        self._sources_dir = config_dir / "sources"

    async def run(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """
        ソースからコンテンツを収集して FetchedItem リストを dict 形式で返す。

        Args:
            params:
                source_id (str): config/sources/ 内のアダプタ設定 ID
                max_items (int): 取得する最大アイテム数（デフォルト 20）

        Returns:
            browse_source.yaml の output スキーマ準拠のリスト

        Raises:
            FileNotFoundError: source_id に対応する YAML が見つからない場合
            ValueError: 未対応の source type の場合
        """
        source_id: str = params["source_id"]
        max_items: int = int(params.get("max_items", 20))

        # ソース設定 YAML 読み込み
        source_yaml = self._sources_dir / f"{source_id}.yaml"
        source_config = load_yaml_config(source_yaml)

        source_type: str = source_config.get("type", "")

        # アダプタ選択
        adapter_cls = _ADAPTER_REGISTRY.get(source_type)
        if adapter_cls is None:
            raise ValueError(
                f"未対応のソースタイプ: '{source_type}' (source_id={source_id}). "
                f"対応タイプ: {list(_ADAPTER_REGISTRY.keys())}"
            )

        adapter: BaseAdapter = adapter_cls(source_config)
        items: list[FetchedItem] = await adapter.fetch(max_items=max_items)

        logger.info(
            "browse_source 完了: source=%s type=%s items=%d",
            source_id,
            source_type,
            len(items),
        )

        # FetchedItem → dict（browse_source output スキーマ準拠）
        return [item.to_dict() for item in items]
