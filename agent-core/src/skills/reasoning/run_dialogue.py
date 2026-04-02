"""
skills/reasoning/run_dialogue.py — マルチエージェント対話オーケストレーション Skill

Zephyr（explorer_and_reporter）と Lynx（critic_and_validator）の
ターン制対話を LLM で駆動し、対話トランスクリプトを返す。

Skill 入出力スキーマ: config/skills/reasoning/run_dialogue.yaml
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from models.llm import LLMClient

logger = logging.getLogger(__name__)

# エージェント定義
_AGENT_ZEPHYR = "zephyr"
_AGENT_LYNX = "lynx"

# システムプロンプト
_ZEPHYR_SYSTEM = """あなたは Zephyr です。役割: explorer_and_reporter。
トピックを広く探索し、新しい視点・洞察・可能性を積極的に提示します。
事実と推測を区別しながら、創造的かつ包括的に考えます。
相手（Lynx）の批判を真摯に受け止め、議論を発展させます。
回答は簡潔に（200字以内）。"""

_LYNX_SYSTEM = """あなたは Lynx です。役割: critic_and_validator。
Zephyr の発言を批判的に検証します。論理的な欠陥・誤り・見落としを指摘します。
建設的な批判と代替案を提示し、議論の質を高めます。
回答は簡潔に（200字以内）。"""


class RunDialogueSkill:
    """
    run_dialogue Skill の実装。

    Zephyr と Lynx の間でターン制対話を実行し、
    トランスクリプトを返す。
    """

    def __init__(
        self,
        llm_client: LLMClient,
        zephyr_system: str = _ZEPHYR_SYSTEM,
        lynx_system: str = _LYNX_SYSTEM,
    ) -> None:
        self._llm = llm_client
        self._zephyr_system = zephyr_system
        self._lynx_system = lynx_system

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        マルチエージェント対話を実行する。

        Args:
            params:
                topic (str): 対話のトピック/質問（必須）
                max_turns (int): 最大ターン数（デフォルト: 4）
                initial_speaker (str): 最初に発言するエージェント（"zephyr" or "lynx"、デフォルト: "zephyr"）
                context (str | None): 追加コンテキスト（背景情報）

        Returns:
            {
                "topic": str,
                "transcript": list[{"agent": str, "turn": int, "content": str}],
                "summary": str,
                "completed_at": str,
            }
        """
        topic: str = params["topic"]
        max_turns: int = int(params.get("max_turns", 4))
        initial_speaker: str = params.get("initial_speaker", _AGENT_ZEPHYR)
        context: str = params.get("context", "")

        if not topic.strip():
            raise ValueError("topic が空です")
        if max_turns < 1 or max_turns > 10:
            raise ValueError("max_turns は 1〜10 の範囲で指定してください")
        if initial_speaker not in (_AGENT_ZEPHYR, _AGENT_LYNX):
            raise ValueError(f"initial_speaker は 'zephyr' または 'lynx' で指定してください")

        transcript: list[dict[str, Any]] = []
        dialogue_history: list[str] = []

        # コンテキストの初期メッセージ
        context_prefix = f"背景情報: {context}\n\n" if context else ""
        opening = f"{context_prefix}トピック: {topic}\n\n対話を開始してください。"

        # ターン制対話ループ
        agents = [initial_speaker]
        other = _AGENT_LYNX if initial_speaker == _AGENT_ZEPHYR else _AGENT_ZEPHYR
        agents.append(other)

        for turn in range(max_turns):
            current_agent = agents[turn % 2]
            system_prompt = (
                self._zephyr_system
                if current_agent == _AGENT_ZEPHYR
                else self._lynx_system
            )

            # 対話履歴を含むユーザーメッセージを構築
            if turn == 0:
                user_message = opening
            else:
                history_text = "\n".join(dialogue_history[-6:])  # 直近 6 発言を文脈に
                user_message = f"これまでの対話:\n{history_text}\n\nあなたの番です。"

            full_prompt = f"System: {system_prompt}\n\nUser: {user_message}"

            try:
                response = await self._llm.generate(
                    prompt=full_prompt,
                    think=False,
                )
                content = response.content.strip()
            except Exception as exc:
                logger.warning(
                    "run_dialogue: turn=%d agent=%s LLM エラー: %s",
                    turn + 1,
                    current_agent,
                    exc,
                )
                content = f"[{current_agent} の応答取得に失敗しました: {exc}]"

            entry = {
                "agent": current_agent,
                "turn": turn + 1,
                "content": content,
            }
            transcript.append(entry)
            dialogue_history.append(f"[{current_agent}] {content}")

            logger.debug(
                "run_dialogue: turn=%d agent=%s content='%s...'",
                turn + 1,
                current_agent,
                content[:50],
            )

        # 対話サマリーの生成
        summary = await self._generate_summary(topic, transcript)

        completed_at = datetime.now(timezone.utc).isoformat()
        logger.info(
            "run_dialogue 完了: topic='%s...' turns=%d",
            topic[:40],
            len(transcript),
        )

        return {
            "topic": topic,
            "transcript": transcript,
            "summary": summary,
            "completed_at": completed_at,
        }

    async def _generate_summary(
        self,
        topic: str,
        transcript: list[dict[str, Any]],
    ) -> str:
        """対話トランスクリプトから要約を生成する。"""
        dialogue_text = "\n".join(
            f"[{t['agent']} ターン{t['turn']}] {t['content']}"
            for t in transcript
        )
        prompt = (
            "System: あなたは対話の要約を簡潔に生成するアシスタントです。\n\n"
            f"User: 以下の対話を 3 文以内で日本語で要約してください。\n\n"
            f"トピック: {topic}\n\n"
            f"対話:\n{dialogue_text}\n\n"
            "要約:"
        )

        try:
            response = await self._llm.generate(
                prompt=prompt,
                think=False,
            )
            return response.content.strip()
        except Exception as exc:
            logger.warning("run_dialogue: サマリー生成失敗: %s", exc)
            return f"対話完了（{len(transcript)} ターン）"
