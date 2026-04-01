"""
skills/action/reply_x.py — X (Twitter) 返信投稿 Skill

Playwright Stealth を使って X の特定ツイートに返信を投稿する。
dry_run=True の場合はブラウザを起動せず、バリデーションのみ実行する。

設計根拠: docs/1_plan.md — Section 11 アウトプット設計
Skill 入出力スキーマ: config/skills/action/reply_x.yaml
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# X ツイート返信の最大文字数
MAX_REPLY_LENGTH: int = 280

# X の有効な tweet URL パターン
_X_URL_PATTERN = re.compile(
    r"^https?://(x\.com|twitter\.com)/[^/]+/status/\d+",
    re.IGNORECASE,
)

# 返信ボタン・入力エリアのセレクタ
_REPLY_BUTTON_SELECTOR = "[data-testid='reply']"
_TWEET_INPUT_SELECTOR = "[data-testid='tweetTextarea_0']"
_SUBMIT_BUTTON_SELECTOR = "[data-testid='tweetButtonInline']"
_POST_CONFIRM_TIMEOUT_MS = 10000


def _is_valid_tweet_url(url: str | None) -> bool:
    """X の tweet URL として有効かどうかを検証する。"""
    if not url:
        return False
    return bool(_X_URL_PATTERN.match(url))


class ReplyXSkill:
    """
    reply_x Skill の実装。

    X の特定ツイートに返信する。dry_run=True の場合はバリデーションのみ。
    """

    def __init__(self, data_dir: Path | str | None = None) -> None:
        if data_dir is None:
            data_dir = Path(__file__).parent.parent.parent.parent.parent.parent / "data"
        self._data_dir = Path(data_dir)

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        X の特定ツイートに返信を投稿する。

        Args:
            params:
                tweet_url (str): 返信先ツイートの URL（必須）
                    例: https://x.com/username/status/1234567890
                text (str): 返信テキスト（必須、最大 280 文字）
                dry_run (bool): True の場合はバリデーションのみ（ブラウザ不使用）
                cookies_file (str | None): Cookie ファイルパス

        Returns:
            {
                "posted": bool,         # 投稿成功フラグ
                "text": str,            # 返信テキスト
                "text_length": int,     # テキスト文字数
                "tweet_url": str,       # 返信先 URL
                "dry_run": bool,        # dry_run フラグ
                "reason": str | None,   # 未投稿の理由（エラー時）
            }
        """
        tweet_url: str | None = params.get("tweet_url")
        text: str = params.get("text", "")
        dry_run: bool = bool(params.get("dry_run", False))
        cookies_file_str: str | None = params.get("cookies_file")

        text_length = len(text)

        # バリデーション: tweet_url 未指定
        if not tweet_url:
            logger.warning("reply_x: tweet_url が指定されていません")
            return {
                "posted": False,
                "text": text,
                "text_length": text_length,
                "tweet_url": tweet_url or "",
                "dry_run": dry_run,
                "reason": "missing_tweet_url",
            }

        # バリデーション: tweet_url フォーマット
        if not _is_valid_tweet_url(tweet_url):
            logger.warning("reply_x: 無効な tweet_url: %s", tweet_url)
            return {
                "posted": False,
                "text": text,
                "text_length": text_length,
                "tweet_url": tweet_url,
                "dry_run": dry_run,
                "reason": "invalid_tweet_url",
            }

        # バリデーション: 空テキスト
        if not text:
            logger.info("reply_x: 空テキストのため返信をスキップ")
            return {
                "posted": False,
                "text": text,
                "text_length": 0,
                "tweet_url": tweet_url,
                "dry_run": dry_run,
                "reason": "empty_text",
            }

        # バリデーション: 文字数超過
        if text_length > MAX_REPLY_LENGTH:
            logger.warning(
                "reply_x: テキストが最大文字数を超過 (%d > %d)",
                text_length,
                MAX_REPLY_LENGTH,
            )
            return {
                "posted": False,
                "text": text,
                "text_length": text_length,
                "tweet_url": tweet_url,
                "dry_run": dry_run,
                "reason": "text_too_long",
            }

        # dry_run モード: ブラウザを使用せずに返す
        if dry_run:
            logger.info("reply_x: dry_run モード。実際の返信はスキップ")
            return {
                "posted": False,
                "text": text,
                "text_length": text_length,
                "tweet_url": tweet_url,
                "dry_run": True,
                "reason": "dry_run",
            }

        # Playwright による実際の返信
        cookies_file = Path(
            cookies_file_str or str(self._data_dir / "browser-profile" / "cookies.json")
        )

        try:
            result = await self._run_with_browser(tweet_url, text, cookies_file)
            return {
                "posted": result["posted"],
                "text": text,
                "text_length": text_length,
                "tweet_url": tweet_url,
                "dry_run": False,
                **({} if result["posted"] else {"reason": result.get("reason", "unknown_error")}),
            }
        except Exception as exc:
            logger.error("reply_x: ブラウザ返信エラー: %s", exc)
            return {
                "posted": False,
                "text": text,
                "text_length": text_length,
                "tweet_url": tweet_url,
                "dry_run": False,
                "reason": str(exc),
            }

    async def _run_with_browser(
        self, tweet_url: str, text: str, cookies_file: Path
    ) -> dict[str, Any]:
        """
        Playwright を使って X の特定ツイートに返信する。

        Args:
            tweet_url: 返信先ツイートの URL
            text: 返信テキスト
            cookies_file: Cookie ファイルパス

        Returns:
            {"posted": bool, "reason": str | None}
        """
        import json

        try:
            from rebrowser_playwright.async_api import async_playwright as _playwright
        except ImportError:
            from playwright.async_api import async_playwright as _playwright

        cookies: list[dict[str, Any]] = []
        if cookies_file.exists():
            try:
                raw = json.loads(cookies_file.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    cookies = raw
                elif isinstance(raw, dict) and "cookies" in raw:
                    cookies = raw["cookies"]
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("reply_x: Cookie ファイル読み込みエラー: %s", exc)

        async with _playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="ja-JP",
            )

            if cookies:
                valid_cookies = [
                    c for c in cookies
                    if c.get("domain") and (
                        "x.com" in c["domain"] or "twitter.com" in c["domain"]
                    )
                ]
                if valid_cookies:
                    await context.add_cookies(valid_cookies)

            page = await context.new_page()
            result = await self._post_reply(page, tweet_url, text)
            await browser.close()
            return result

    async def _post_reply(self, page: Any, tweet_url: str, text: str) -> dict[str, Any]:
        """
        Playwright ページオブジェクトを使ってツイートに返信する。

        テスト可能にするため、page を引数として受け取る。

        Args:
            page: Playwright の Page オブジェクト
            tweet_url: 返信先ツイートの URL
            text: 返信テキスト

        Returns:
            {"posted": bool, "reason": str | None}
        """
        try:
            # ツイートページへ移動
            await page.goto(tweet_url, wait_until="domcontentloaded", timeout=30000)

            # 返信ボタンをクリック
            await page.wait_for_selector(_REPLY_BUTTON_SELECTOR, timeout=_POST_CONFIRM_TIMEOUT_MS)
            await page.click(_REPLY_BUTTON_SELECTOR)

            # テキスト入力エリアに返信テキストを入力
            await page.wait_for_selector(_TWEET_INPUT_SELECTOR, timeout=_POST_CONFIRM_TIMEOUT_MS)
            await page.fill(_TWEET_INPUT_SELECTOR, text)

            # 投稿ボタンをクリック
            await page.wait_for_selector(_SUBMIT_BUTTON_SELECTOR, timeout=_POST_CONFIRM_TIMEOUT_MS)
            await page.click(_SUBMIT_BUTTON_SELECTOR)

            logger.info("reply_x: 返信投稿完了 tweet_url=%s length=%d", tweet_url, len(text))
            return {"posted": True}

        except Exception as exc:
            logger.error("reply_x: 返信投稿エラー: %s", exc)
            return {"posted": False, "reason": str(exc)}
