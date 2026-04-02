"""
skills/output/generate_daily_digest.py — Daily Digest 生成 Skill

1日の収集情報・活動サマリーを LLM で生成する。
dry_run=True の場合は LLM を呼び出さず、バリデーションのみ実行する。

設計根拠: docs/1_plan.md — Section 11 アウトプット設計
Skill 入出力スキーマ: config/skills/output/generate_daily_digest.yaml
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)

# デフォルトモデル（サマリー生成は中型モデルで十分）
_DEFAULT_MODEL: str = "llama3.1:latest"


def _build_digest_prompt(entries: list[dict[str, Any]], date_str: str) -> str:
    """Daily Digest 生成用のプロンプトを組み立てる。"""
    # エントリ一覧をテキスト化
    entry_lines: list[str] = []
    for i, entry in enumerate(entries, 1):
        title = entry.get("title", "（タイトルなし）")
        summary = entry.get("summary", "")
        source = entry.get("source", "")
        line = f"{i}. {title}"
        if source:
            line += f" [{source}]"
        if summary:
            line += f"\n   {summary}"
        entry_lines.append(line)

    entries_text = "\n".join(entry_lines)

    return (
        f"日付: {date_str}\n\n"
        f"## 収集した情報 ({len(entries)}件)\n\n"
        f"{entries_text}\n\n"
        f"## 指示\n\n"
        f"上記の収集情報をもとに、1日の Daily Digest（日次サマリー）を Markdown 形式で生成してください。\n"
        f"- タイトルは「{date_str} Daily Digest」の形式にしてください\n"
        f"- 主要トピックを箇条書きでまとめてください\n"
        f"- 注目記事・トピックをピックアップしてください\n"
        f"- 全体的なトレンドや気づきをまとめてください\n"
        f"- 日本語で記述してください\n"
        f"Markdown 本文のみを出力してください（前置きや説明は不要です）。"
    )


class GenerateDailyDigestSkill:
    """
    generate_daily_digest Skill の実装。

    1日の収集情報・活動サマリーを LLM で生成する。
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
        Daily Digest を生成する。

        Args:
            params:
                entries (list[dict]): 収集したエントリ一覧（必須）
                    各エントリに title, summary, source 等を含む
                date (str | None): 対象日（YYYY-MM-DD）。省略時は今日
                dry_run (bool): True の場合は LLM を呼ばずに返す
                model (str | None): 使用モデル

        Returns:
            {
                "generated": bool,       # 生成成功フラグ
                "title": str,            # ダイジェストタイトル
                "body": str,             # Markdown 本文（エラー時は空文字列）
                "entry_count": int,      # 入力エントリ数
                "date": str,             # 対象日
                "dry_run": bool,         # dry_run フラグ
                "reason": str | None,    # 未生成の理由（エラー時）
            }
        """
        entries: list[dict[str, Any]] = params.get("entries") or []
        date_str: str = params.get("date") or str(date.today())
        dry_run: bool = bool(params.get("dry_run", False))
        model: str = params.get("model") or self._model

        entry_count = len(entries)

        # バリデーション: 空エントリ
        if not entries:
            logger.info("generate_daily_digest: エントリが空のため生成をスキップ")
            return {
                "generated": False,
                "title": "",
                "body": "",
                "entry_count": 0,
                "date": date_str,
                "dry_run": dry_run,
                "reason": "empty_entries",
            }

        # dry_run モード
        if dry_run:
            logger.info("generate_daily_digest: dry_run モード。LLM 呼び出しをスキップ")
            return {
                "generated": False,
                "title": f"{date_str} Daily Digest",
                "body": "",
                "entry_count": entry_count,
                "date": date_str,
                "dry_run": True,
                "reason": "dry_run",
            }

        # LLM による生成
        prompt = _build_digest_prompt(entries, date_str)
        title = f"{date_str} Daily Digest"

        try:
            response = await self._llm.generate(
                prompt=prompt,
                model=model,
                think=False,
            )
            body: str = response.content

            logger.info(
                "generate_daily_digest: 生成完了 date=%s entries=%d chars=%d",
                date_str,
                entry_count,
                len(body),
            )
            return {
                "generated": True,
                "title": title,
                "body": body,
                "entry_count": entry_count,
                "date": date_str,
                "dry_run": False,
            }

        except Exception as exc:
            logger.error("generate_daily_digest: LLM 生成エラー: %s", exc)
            return {
                "generated": False,
                "title": title,
                "body": "",
                "entry_count": entry_count,
                "date": date_str,
                "dry_run": False,
                "reason": str(exc),
            }
