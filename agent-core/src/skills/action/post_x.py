"""
skills/action/post_x.py — X (Twitter) 投稿 Skill

Playwright Stealth を使って X にツイートを投稿する。
dry_run=True の場合はブラウザを起動せず、バリデーションのみ実行する。

設計根拠: docs/1_plan.md — Section 11 アウトプット設計
Skill 入出力スキーマ: config/skills/action/post_x.yaml
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# X ツイートの最大文字数
MAX_TWEET_LENGTH: int = 280

# ツイート投稿ボタンのセレクタ（X の DOM）
_COMPOSE_BUTTON_SELECTOR = "[data-testid='SideNav_NewTweet_Button']"
_TWEET_INPUT_SELECTOR = "[data-testid='tweetTextarea_0']"
_SUBMIT_BUTTON_SELECTOR = "[data-testid='tweetButtonInline']"
# 投稿成功の確認セレクタ（送信完了後に消えるテキスト入力エリア）
_POST_CONFIRM_TIMEOUT_MS = 10000


class PostXSkill:
    """
    post_x Skill の実装。

    X にツイートを投稿する。dry_run=True の場合はバリデーションのみ。
    """

    def __init__(self, data_dir: Path | str | None = None) -> None:
        if data_dir is None:
            data_dir = Path(__file__).parent.parent.parent.parent.parent.parent / "data"
        self._data_dir = Path(data_dir)

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        X にツイートを投稿する。

        Args:
            params:
                text (str): 投稿するテキスト（必須）
                dry_run (bool): True の場合はバリデーションのみ（ブラウザ不使用）
                cookies_file (str | None): Cookie ファイルパス

        Returns:
            {
                "posted": bool,         # 投稿成功フラグ
                "text": str,            # 投稿テキスト
                "text_length": int,     # テキスト文字数
                "dry_run": bool,        # dry_run フラグ
                "reason": str | None,   # 未投稿の理由（エラー時）
            }
        """
        text: str = params.get("text", "")
        dry_run: bool = bool(params.get("dry_run", False))
        cookies_file_str: str | None = params.get("cookies_file")

        text_length = len(text)

        # バリデーション: 空テキスト
        if not text:
            logger.info("post_x: 空テキストのため投稿をスキップ")
            return {
                "posted": False,
                "text": text,
                "text_length": 0,
                "dry_run": dry_run,
                "reason": "empty_text",
            }

        # バリデーション: 文字数超過
        if text_length > MAX_TWEET_LENGTH:
            logger.warning(
                "post_x: テキストが最大文字数を超過 (%d > %d)",
                text_length,
                MAX_TWEET_LENGTH,
            )
            return {
                "posted": False,
                "text": text,
                "text_length": text_length,
                "dry_run": dry_run,
                "reason": "text_too_long",
            }

        # dry_run モード: ブラウザを使用せずに返す
        if dry_run:
            logger.info("post_x: dry_run モード。実際の投稿はスキップ")
            return {
                "posted": False,
                "text": text,
                "text_length": text_length,
                "dry_run": True,
                "reason": "dry_run",
            }

        # Playwright による実際の投稿
        cookies_file = Path(
            cookies_file_str or str(self._data_dir / "browser-profile" / "cookies.json")
        )

        try:
            result = await self._run_with_browser(text, cookies_file)
            return {
                "posted": result["posted"],
                "text": text,
                "text_length": text_length,
                "dry_run": False,
                **({} if result["posted"] else {"reason": result.get("reason", "unknown_error")}),
            }
        except Exception as exc:
            logger.error("post_x: ブラウザ投稿エラー: %s", exc)
            return {
                "posted": False,
                "text": text,
                "text_length": text_length,
                "dry_run": False,
                "reason": str(exc),
            }

    async def _run_with_browser(
        self, text: str, cookies_file: Path
    ) -> dict[str, Any]:
        """
        Playwright を使って X にツイートを投稿する。

        Args:
            text: 投稿テキスト
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
                logger.warning("post_x: Cookie ファイル読み込みエラー: %s", exc)

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
            await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)

            result = await self._post_tweet(page, text)
            await browser.close()
            return result

    async def _post_tweet(self, page: Any, text: str) -> dict[str, Any]:
        """
        Playwright ページオブジェクトを使ってツイートを投稿する。

        テスト可能にするため、page を引数として受け取る。

        Args:
            page: Playwright の Page オブジェクト
            text: 投稿テキスト

        Returns:
            {"posted": bool, "reason": str | None}
        """
        try:
            # ツイート作成ボタンをクリック
            compose_btn = await page.query_selector(_COMPOSE_BUTTON_SELECTOR)
            if compose_btn:
                await page.click(_COMPOSE_BUTTON_SELECTOR)
            else:
                # ホームページに既にテキスト入力エリアがある場合
                logger.debug("post_x: compose button not found, trying direct input")

            # テキスト入力エリアに文字を入力
            await page.wait_for_selector(_TWEET_INPUT_SELECTOR, timeout=_POST_CONFIRM_TIMEOUT_MS)
            await page.fill(_TWEET_INPUT_SELECTOR, text)

            # 投稿ボタンをクリック
            await page.wait_for_selector(_SUBMIT_BUTTON_SELECTOR, timeout=_POST_CONFIRM_TIMEOUT_MS)
            await page.click(_SUBMIT_BUTTON_SELECTOR)

            logger.info("post_x: ツイート投稿完了 length=%d", len(text))
            return {"posted": True}

        except Exception as exc:
            logger.error("post_x: ツイート投稿エラー: %s", exc)
            return {"posted": False, "reason": str(exc)}
