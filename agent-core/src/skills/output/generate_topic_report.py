"""
skills/output/generate_topic_report.py — Topic Report 生成 Skill

特定トピックに関する収集エントリをもとに深掘りレポートを LLM で生成する。
dry_run=True の場合は LLM を呼び出さず、バリデーションのみ実行する。

設計根拠: docs/1_plan.md — Section 11 アウトプット設計
Skill 入出力スキーマ: config/skills/output/generate_topic_report.yaml
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# デフォルトモデル（レポート生成は中型モデルで十分）
_DEFAULT_MODEL: str = "llama3.1:latest"


def _build_report_prompt(topic: str, entries: list[dict[str, Any]]) -> str:
    """Topic Report 生成用のプロンプトを組み立てる。"""
    entry_lines: list[str] = []
    for i, entry in enumerate(entries, 1):
        title = entry.get("title", "（タイトルなし）")
        summary = entry.get("summary", "")
        source = entry.get("source", "")
        url = entry.get("url", "")
        line = f"{i}. {title}"
        if source:
            line += f" [{source}]"
        if url:
            line += f"\n   URL: {url}"
        if summary:
            line += f"\n   {summary}"
        entry_lines.append(line)

    entries_text = "\n".join(entry_lines)

    return (
        f"トピック: {topic}\n\n"
        f"## 関連収集情報 ({len(entries)}件)\n\n"
        f"{entries_text}\n\n"
        f"## 指示\n\n"
        f"上記の収集情報をもとに、「{topic}」についての深掘りレポートを Markdown 形式で生成してください。\n"
        f"- タイトルは「{topic} レポート」の形式にしてください\n"
        f"- 概要（Overview）セクション\n"
        f"- 主要な動向・発見事項\n"
        f"- 注目すべきポイント\n"
        f"- 今後の展望・考察\n"
        f"- 日本語で記述してください\n"
        f"Markdown 本文のみを出力してください（前置きや説明は不要です）。"
    )


class GenerateTopicReportSkill:
    """
    generate_topic_report Skill の実装。

    特定トピックの深掘りレポートを LLM で生成する。
    dry_run=True の場合はバリデーションのみ。
    """

    def __init__(
        self,
        llm_client: Any,
        model: str | None = None,
    ) -> None:
        self._llm = llm_client
        self._model = model or _DEFAULT_MODEL

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Topic Report を生成する。

        Args:
            params:
                topic (str): レポート対象トピック（必須）
                entries (list[dict]): 関連エントリ一覧（必須）
                    各エントリに title, summary, source, url 等を含む
                dry_run (bool): True の場合は LLM を呼ばずに返す
                model (str | None): 使用モデル

        Returns:
            {
                "generated": bool,       # 生成成功フラグ
                "topic": str,            # 対象トピック
                "title": str,            # レポートタイトル
                "body": str,             # Markdown 本文（エラー時は空文字列）
                "entry_count": int,      # 入力エントリ数
                "dry_run": bool,         # dry_run フラグ
                "reason": str | None,    # 未生成の理由（エラー時）
            }
        """
        topic: str | None = params.get("topic")
        entries: list[dict[str, Any]] = params.get("entries") or []
        dry_run: bool = bool(params.get("dry_run", False))
        model: str = params.get("model") or self._model

        entry_count = len(entries)

        # バリデーション: 空トピック
        if not topic:
            logger.warning("generate_topic_report: topic が空のため生成をスキップ")
            return {
                "generated": False,
                "topic": topic or "",
                "title": "",
                "body": "",
                "entry_count": entry_count,
                "dry_run": dry_run,
                "reason": "empty_topic",
            }

        # バリデーション: 空エントリ
        if not entries:
            logger.info("generate_topic_report: エントリが空のため生成をスキップ")
            return {
                "generated": False,
                "topic": topic,
                "title": "",
                "body": "",
                "entry_count": 0,
                "dry_run": dry_run,
                "reason": "empty_entries",
            }

        title = f"{topic} レポート"

        # dry_run モード
        if dry_run:
            logger.info("generate_topic_report: dry_run モード。LLM 呼び出しをスキップ")
            return {
                "generated": False,
                "topic": topic,
                "title": title,
                "body": "",
                "entry_count": entry_count,
                "dry_run": True,
                "reason": "dry_run",
            }

        # LLM による生成
        prompt = _build_report_prompt(topic, entries)

        try:
            response = await self._llm.generate(
                prompt=prompt,
                model=model,
                think=False,
            )
            body: str = response.content

            logger.info(
                "generate_topic_report: 生成完了 topic=%s entries=%d chars=%d",
                topic,
                entry_count,
                len(body),
            )
            return {
                "generated": True,
                "topic": topic,
                "title": title,
                "body": body,
                "entry_count": entry_count,
                "dry_run": False,
            }

        except Exception as exc:
            logger.error("generate_topic_report: LLM 生成エラー: %s", exc)
            return {
                "generated": False,
                "topic": topic,
                "title": title,
                "body": "",
                "entry_count": entry_count,
                "dry_run": False,
                "reason": str(exc),
            }
