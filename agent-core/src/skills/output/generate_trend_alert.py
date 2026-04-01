"""
skills/output/generate_trend_alert.py — Trend Alert 生成 Skill

急上昇トピック・異常値の通知テキストを LLM で生成する。
dry_run=True の場合は LLM を呼び出さず、バリデーションのみ実行する。

設計根拠: docs/1_plan.md — Section 11 アウトプット設計
Skill 入出力スキーマ: config/skills/output/generate_trend_alert.yaml
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# アラート生成の最低スコア閾値（0.0〜1.0）
MIN_ALERT_SCORE: float = 0.7

# デフォルトモデル（短文アラートは小型モデルで十分）
_DEFAULT_MODEL: str = "qwen3.5:14b"


def _build_alert_prompt(topic: str, score: float, entries: list[dict[str, Any]]) -> str:
    """Trend Alert 生成用のプロンプトを組み立てる。"""
    entry_lines: list[str] = []
    for i, entry in enumerate(entries, 1):
        title = entry.get("title", "（タイトルなし）")
        source = entry.get("source", "")
        line = f"{i}. {title}"
        if source:
            line += f" [{source}]"
        entry_lines.append(line)

    entries_text = "\n".join(entry_lines)
    score_pct = int(score * 100)

    return (
        f"トレンドトピック: {topic}\n"
        f"トレンドスコア: {score:.2f}（{score_pct}%）\n\n"
        f"## 関連記事 ({len(entries)}件)\n\n"
        f"{entries_text}\n\n"
        f"## 指示\n\n"
        f"上記のトレンドトピックについて、Discord に投稿するアラートメッセージを生成してください。\n"
        f"- 短く簡潔に（3〜5文程度）\n"
        f"- トピック名とトレンドスコアを含める\n"
        f"- 注目の理由を1〜2文で説明\n"
        f"- 代表的な記事タイトルを1件引用\n"
        f"- 絵文字を使って読みやすくする\n"
        f"- 日本語で記述してください\n"
        f"アラートメッセージのみを出力してください（前置きや説明は不要です）。"
    )


class GenerateTrendAlertSkill:
    """
    generate_trend_alert Skill の実装。

    急上昇トピックの通知テキストを LLM で生成する。
    スコアが MIN_ALERT_SCORE 未満の場合はスキップ。
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
        Trend Alert テキストを生成する。

        Args:
            params:
                topic (str): トレンドトピック名（必須）
                score (float): トレンドスコア 0.0〜1.0（必須）
                entries (list[dict]): 関連エントリ一覧（必須）
                dry_run (bool): True の場合は LLM を呼ばずに返す
                model (str | None): 使用モデル

        Returns:
            {
                "generated": bool,       # 生成成功フラグ
                "topic": str,            # トレンドトピック
                "score": float,          # トレンドスコア
                "alert_text": str,       # アラートテキスト（エラー時は空文字列）
                "entry_count": int,      # 入力エントリ数
                "dry_run": bool,         # dry_run フラグ
                "reason": str | None,    # 未生成の理由（エラー時）
            }
        """
        topic: str | None = params.get("topic")
        score: float = float(params.get("score", 0.0))
        entries: list[dict[str, Any]] = params.get("entries") or []
        dry_run: bool = bool(params.get("dry_run", False))
        model: str = params.get("model") or self._model

        entry_count = len(entries)

        # バリデーション: 空トピック
        if not topic:
            logger.warning("generate_trend_alert: topic が空のため生成をスキップ")
            return {
                "generated": False,
                "topic": topic or "",
                "score": score,
                "alert_text": "",
                "entry_count": entry_count,
                "dry_run": dry_run,
                "reason": "empty_topic",
            }

        # バリデーション: 空エントリ
        if not entries:
            logger.info("generate_trend_alert: エントリが空のため生成をスキップ")
            return {
                "generated": False,
                "topic": topic,
                "score": score,
                "alert_text": "",
                "entry_count": 0,
                "dry_run": dry_run,
                "reason": "empty_entries",
            }

        # バリデーション: スコア閾値
        if score < MIN_ALERT_SCORE:
            logger.info(
                "generate_trend_alert: スコアが閾値未満のためスキップ (%.2f < %.2f)",
                score,
                MIN_ALERT_SCORE,
            )
            return {
                "generated": False,
                "topic": topic,
                "score": score,
                "alert_text": "",
                "entry_count": entry_count,
                "dry_run": dry_run,
                "reason": "score_below_threshold",
            }

        # dry_run モード
        if dry_run:
            logger.info("generate_trend_alert: dry_run モード。LLM 呼び出しをスキップ")
            return {
                "generated": False,
                "topic": topic,
                "score": score,
                "alert_text": "",
                "entry_count": entry_count,
                "dry_run": True,
                "reason": "dry_run",
            }

        # LLM による生成
        prompt = _build_alert_prompt(topic, score, entries)

        try:
            response = await self._llm.generate(
                prompt=prompt,
                model=model,
                think=False,
            )
            alert_text: str = response.content

            logger.info(
                "generate_trend_alert: 生成完了 topic=%s score=%.2f chars=%d",
                topic,
                score,
                len(alert_text),
            )
            return {
                "generated": True,
                "topic": topic,
                "score": score,
                "alert_text": alert_text,
                "entry_count": entry_count,
                "dry_run": False,
            }

        except Exception as exc:
            logger.error("generate_trend_alert: LLM 生成エラー: %s", exc)
            return {
                "generated": False,
                "topic": topic,
                "score": score,
                "alert_text": "",
                "entry_count": entry_count,
                "dry_run": False,
                "reason": str(exc),
            }
