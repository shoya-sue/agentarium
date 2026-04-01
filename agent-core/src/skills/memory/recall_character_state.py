"""
skills/memory/recall_character_state.py — キャラクター状態取得 Skill

character_state コレクションから指定キャラクターの最新 L3/L4/L5 状態を取得する。

character_name + state_type で payload フィルタし、
stored_at 降順で最新の 1 件を返す。

Phase 3 Skill
Skill 入出力スキーマ: config/skills/memory/recall_character_state.yaml
"""

from __future__ import annotations

import json
import logging
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
)

logger = logging.getLogger(__name__)

# 有効な state_type の一覧（L3/L4/L5 に対応）
_VALID_STATE_TYPES = {"emotional", "cognitive", "trust"}

# character_state コレクション名
_COLLECTION_NAME = "character_state"


class RecallCharacterStateSkill:
    """
    recall_character_state Skill の実装。

    Qdrant character_state コレクションから最新のキャラクター状態を取得する。
    payload フィルタ（character_name + state_type）で絞り込み、
    stored_at 降順の先頭 1 件を返す。
    """

    def __init__(self, qdrant_host: str = "localhost", qdrant_port: int = 6333) -> None:
        self._client = QdrantClient(host=qdrant_host, port=qdrant_port)

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        character_state コレクションから最新の状態を取得する。

        Args:
            params:
                character_name (str): キャラクター名
                state_type (str): 状態種別 ("emotional" | "cognitive" | "trust")
                dry_run (bool): True の場合は検索を行わない

        Returns:
            {
                "found": bool,
                "state": dict | None,
                "stored_at": str | None,    # ISO8601 形式
                "character_name": str,
                "state_type": str,
                "reason": str | None,
            }
        """
        character_name: str = params.get("character_name", "")
        state_type: str = params.get("state_type", "")
        dry_run: bool = params.get("dry_run", False)

        # ---- バリデーション ----
        if not character_name:
            return self._not_found("empty_character_name", character_name, state_type)

        if state_type not in _VALID_STATE_TYPES:
            return self._not_found("invalid_state_type", character_name, state_type)

        # ---- dry_run モード ----
        if dry_run:
            return self._not_found("dry_run", character_name, state_type)

        # ---- Qdrant 検索 ----
        scroll_filter = Filter(
            must=[
                FieldCondition(
                    key="character_name",
                    match=MatchValue(value=character_name),
                ),
                FieldCondition(
                    key="state_type",
                    match=MatchValue(value=state_type),
                ),
            ]
        )

        try:
            points, _ = self._client.scroll(
                collection_name=_COLLECTION_NAME,
                scroll_filter=scroll_filter,
                limit=100,  # 全件取得後に stored_at でソートして最新を選択
                with_payload=True,
            )
        except Exception as exc:
            logger.warning(
                "character_state 検索エラー: character=%s type=%s err=%s",
                character_name,
                state_type,
                exc,
            )
            return self._not_found("search_error", character_name, state_type)

        if not points:
            logger.debug(
                "character_state 未発見: character=%s type=%s",
                character_name,
                state_type,
            )
            return self._not_found(None, character_name, state_type)

        # stored_at 降順でソートして最新 1 件を取得
        sorted_points = sorted(
            points,
            key=lambda p: p.payload.get("stored_at", ""),
            reverse=True,
        )
        latest = sorted_points[0]
        payload = latest.payload

        # state フィールドが JSON 文字列として保存されていた場合はデシリアライズ
        raw_state = payload.get("state")
        if isinstance(raw_state, str):
            try:
                state_dict: dict | None = json.loads(raw_state)
            except json.JSONDecodeError:
                state_dict = None
        else:
            state_dict = raw_state

        logger.info(
            "character_state 取得: character=%s type=%s stored_at=%s",
            character_name,
            state_type,
            payload.get("stored_at"),
        )

        return {
            "found": True,
            "state": state_dict,
            "stored_at": payload.get("stored_at"),
            "character_name": character_name,
            "state_type": state_type,
            "reason": None,
        }

    def _not_found(
        self, reason: str | None, character_name: str, state_type: str
    ) -> dict[str, Any]:
        """未発見・バリデーション失敗・dry_run 時の応答を返す。"""
        return {
            "found": False,
            "state": None,
            "stored_at": None,
            "character_name": character_name,
            "state_type": state_type,
            "reason": reason,
        }
