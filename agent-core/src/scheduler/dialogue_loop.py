"""
scheduler/dialogue_loop.py — Zephyr/Lynx 対話ループ

定期的に run_dialogue を呼び出し、トランスクリプトを Discord に
ターンごとに投稿する。各発言を個別メッセージとして送ることで
自然な会話の流れを演出する。

設計:
  - AgentLoop とは独立して動作
  - recall_related で最近の技術トレンドからトピックを自動選択
  - ターン間に turn_delay_seconds を挟んでリアルな会話感を演出
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# デフォルト設定
_DEFAULT_INTERVAL_SECONDS: float = 300.0   # 5分ごとに対話セッション開始
_DEFAULT_TURN_DELAY_SECONDS: float = 4.0   # ターン間の遅延（秒）
_DEFAULT_MAX_TURNS: int = 4
_DEFAULT_RECALL_QUERY: str = "技術トレンド 最新情報"
_DEFAULT_TOPIC: str = "最近の技術トレンドについて議論してください"

# キャラクター名 → Discord 表示名のマッピング
_CHARACTER_DISPLAY_NAMES: dict[str, str] = {
    "zephyr": "Zephyr",
    "lynx": "Lynx",
}


class DialogueLoop:
    """
    Zephyr と Lynx の定期対話ループ。

    Args:
        run_dialogue_fn: run_dialogue Skill の呼び出し関数
        send_discord_fn: send_discord Skill の呼び出し関数
        recall_related_fn: recall_related Skill の呼び出し関数（トピック選択用）
        interval_seconds: 対話セッションの間隔（秒）
        turn_delay_seconds: ターン間の遅延（秒）
        max_turns: 1セッションあたりの最大ターン数
    """

    def __init__(
        self,
        run_dialogue_fn: Any,
        send_discord_fn: Any,
        recall_related_fn: Any,
        interval_seconds: float = _DEFAULT_INTERVAL_SECONDS,
        turn_delay_seconds: float = _DEFAULT_TURN_DELAY_SECONDS,
        max_turns: int = _DEFAULT_MAX_TURNS,
    ) -> None:
        self._run_dialogue = run_dialogue_fn
        self._send_discord = send_discord_fn
        self._recall_related = recall_related_fn
        self._interval_seconds = interval_seconds
        self._turn_delay_seconds = turn_delay_seconds
        self._max_turns = max_turns
        self._running: bool = False
        self._session_count: int = 0

    async def start(self) -> None:
        """対話ループを開始する。"""
        if self._running:
            logger.warning("DialogueLoop は既に起動中です")
            return
        self._running = True
        logger.info(
            "DialogueLoop 開始: interval=%.0fs turns=%d",
            self._interval_seconds,
            self._max_turns,
        )
        await self._run_loop()

    async def stop(self) -> None:
        """対話ループを停止する。"""
        self._running = False
        logger.info("DialogueLoop 停止 (sessions=%d)", self._session_count)

    # ------------------------------------------------------------------
    # ループ制御
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """メインループ: interval_seconds ごとに対話セッションを実行する。"""
        # 最初のセッションは interval_seconds 待ってから開始（情報収集が先に走るため）
        logger.info("DialogueLoop: 初回対話まで %.0f 秒待機", self._interval_seconds)
        await asyncio.sleep(self._interval_seconds)

        while self._running:
            await self._run_session()
            if self._running:
                await asyncio.sleep(self._interval_seconds)

        self._running = False

    # ------------------------------------------------------------------
    # 対話セッション
    # ------------------------------------------------------------------

    async def _run_session(self) -> None:
        """1回の対話セッションを実行する。"""
        self._session_count += 1
        logger.info("DialogueLoop セッション開始: session=%d", self._session_count)

        # 1. トピック選択
        topic = await self._select_topic()

        # 2. 対話生成
        try:
            result = await self._run_dialogue({
                "topic": topic,
                "max_turns": self._max_turns,
                "initial_speaker": "zephyr",
            })
        except Exception as exc:
            logger.error("DialogueLoop: run_dialogue エラー: %s", exc)
            return

        transcript: list[dict[str, Any]] = result.get("transcript", [])
        if not transcript:
            logger.warning("DialogueLoop: トランスクリプトが空です")
            return

        # 3. 各ターンを Discord に投稿
        await self._post_transcript(topic, transcript)

        logger.info(
            "DialogueLoop セッション完了: session=%d turns=%d topic='%s...'",
            self._session_count,
            len(transcript),
            topic[:40],
        )

    async def _select_topic(self) -> str:
        """
        recall_related で最近の記憶を取得し、トピックを選択する。
        記憶がない場合はデフォルトトピックを使用する。
        """
        try:
            recalled = await self._recall_related({
                "query": _DEFAULT_RECALL_QUERY,
                "limit": 5,
            })
            items = recalled if isinstance(recalled, list) else recalled.get("items", [])
            if items:
                # 最初のアイテムのタイトルまたはコンテンツをトピックに使用
                first = items[0]
                title = first.get("title") or first.get("content", "")[:80]
                if title:
                    topic = f"{title} について議論してください"
                    logger.info("DialogueLoop: トピック選択: '%s...'", topic[:40])
                    return topic
        except Exception as exc:
            logger.warning("DialogueLoop: トピック選択エラー: %s", exc)

        return _DEFAULT_TOPIC

    async def _post_transcript(
        self,
        topic: str,
        transcript: list[dict[str, Any]],
    ) -> None:
        """
        トランスクリプトの各ターンを Discord に投稿する。
        ターン間に turn_delay_seconds 秒の遅延を挟む。
        """
        # セッション開始を告知（任意）
        header = f"💬 **対話トピック**: {topic}"
        try:
            await self._send_discord({"message": header, "username": "Agentarium"})
            await asyncio.sleep(self._turn_delay_seconds)
        except Exception as exc:
            logger.warning("DialogueLoop: ヘッダー投稿エラー: %s", exc)

        # 各ターンを投稿
        for entry in transcript:
            agent: str = entry.get("agent", "agent")
            content: str = entry.get("content", "").strip()
            if not content:
                continue

            username = _CHARACTER_DISPLAY_NAMES.get(agent, agent.capitalize())
            try:
                await self._send_discord({
                    "message": content,
                    "character_name": agent,   # キャラクター別 Webhook URL を選択
                    "username": username,       # Webhook 名が未設定の場合のフォールバック表示名
                })
                logger.info(
                    "DialogueLoop: 投稿完了 agent=%s length=%d",
                    agent,
                    len(content),
                )
            except Exception as exc:
                logger.warning("DialogueLoop: Discord 投稿エラー agent=%s: %s", agent, exc)

            # 次のターンまで待機（最後のターン後は不要）
            if entry != transcript[-1]:
                await asyncio.sleep(self._turn_delay_seconds)
