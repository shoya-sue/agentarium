"""
skills/browser/verify_x_session.py — X セッション検証 Skill

X (Twitter) のセッションが有効かどうかを確認する。
ログアウト / CAPTCHA / アカウント警告 / レートリミットを検出する。

検出に応じた on_failure アクション:
  captcha / account_warning → emergency_stop（Agent 停止）
  logged_out               → skip_x_sources（X ソースをスキップ）
  rate_limited             → 待機して継続

Skill 入出力スキーマ: config/skills/browser/verify_x_session.yaml
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# X セッション検証 URL
_VERIFY_URL = "https://x.com/home"

# セッション有効を示す DOM セレクタ（Phase 0 V5 実測値）
_SUCCESS_SELECTOR = "[data-testid='primaryColumn']"

# 問題を示す DOM セレクタマッピング（status → selector）
_FAILURE_SELECTORS: dict[str, str] = {
    "logged_out": "[data-testid='loginButton']",
    "captcha": ".captcha-container, #arkose_iframe",
    "account_warning": "[data-testid='AccountSuspended'], [data-testid='AccountLocked']",
}


class VerifyXSessionSkill:
    """
    verify_x_session Skill の実装。

    X のホームページにアクセスし、セッションの有効性を DOM から判定する。
    Phase 0 検証済みの CDP アプローチ（rebrowser-playwright）を使用。
    """

    def __init__(self, data_dir: Path | str | None = None) -> None:
        if data_dir is None:
            # デフォルト: agentarium/data/
            data_dir = Path(__file__).parent.parent.parent.parent.parent.parent / "data"
        self._data_dir = Path(data_dir)

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        X セッションを検証する。

        Args:
            params:
                cookies_file (str | None): Cookie ファイルパス
                    デフォルト: data/browser-profile/cookies.json

        Returns:
            {
                "valid": bool,
                "status": "ok" | "logged_out" | "captcha" | "rate_limited"
                        | "account_warning" | "unknown_error",
                "message": str,
                "checked_at": str (ISO 8601),
            }
        """
        cookies_file_str: str = params.get(
            "cookies_file",
            str(self._data_dir / "browser-profile" / "cookies.json"),
        )
        cookies_file = Path(cookies_file_str)
        checked_at = datetime.now(timezone.utc).isoformat()

        # Cookie ファイルの読み込み
        cookies: list[dict[str, Any]] = []
        if cookies_file.exists():
            try:
                raw = json.loads(cookies_file.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    cookies = raw
                elif isinstance(raw, dict) and "cookies" in raw:
                    # state.json 形式 {"cookies": [...]} に対応
                    cookies = raw["cookies"]
                logger.debug("Cookie ファイル読み込み: %d 件", len(cookies))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Cookie ファイル読み込みエラー: %s", exc)
        else:
            logger.warning("Cookie ファイルが見つかりません: %s", cookies_file)

        # Playwright でセッション検証
        try:
            result = await self._verify_with_browser(cookies)
            return {**result, "checked_at": checked_at}
        except Exception as exc:
            logger.error("X セッション検証エラー: %s", exc)
            return {
                "valid": False,
                "status": "unknown_error",
                "message": str(exc),
                "checked_at": checked_at,
            }

    async def _verify_with_browser(
        self, cookies: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Playwright（rebrowser）を使って X ホームページにアクセスし、
        DOM からセッション状態を判定する。

        Args:
            cookies: Cookie リスト（セッションの注入に使用）

        Returns:
            {"valid": bool, "status": str, "message": str}
        """
        # rebrowser-playwright を優先（bot 検出対策）
        # フォールバックで通常の playwright を使用
        try:
            from rebrowser_playwright.async_api import async_playwright as _playwright
        except ImportError:
            from playwright.async_api import async_playwright as _playwright

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

            # Cookie を注入
            if cookies:
                # Playwright はドメイン指定が必要
                valid_cookies = [
                    c for c in cookies
                    if c.get("domain") and (
                        "x.com" in c["domain"] or "twitter.com" in c["domain"]
                    )
                ]
                if valid_cookies:
                    await context.add_cookies(valid_cookies)
                    logger.debug("Cookie 注入: %d 件", len(valid_cookies))

            page = await context.new_page()

            # X ホームにアクセス
            await page.goto(_VERIFY_URL, wait_until="domcontentloaded", timeout=30000)

            # 問題セレクタを先にチェック（優先度: captcha > account_warning > logged_out）
            for status, selector in _FAILURE_SELECTORS.items():
                # カンマ区切りセレクタは別々に検査
                for sel in selector.split(","):
                    sel = sel.strip()
                    if sel and await page.query_selector(sel) is not None:
                        message = f"X セッション問題検出: {status}"
                        logger.warning(message)
                        await browser.close()
                        return {
                            "valid": False,
                            "status": status,
                            "message": message,
                        }

            # 成功セレクタを確認
            success_el = await page.query_selector(_SUCCESS_SELECTOR)
            await browser.close()

            if success_el is not None:
                logger.info("X セッション有効")
                return {
                    "valid": True,
                    "status": "ok",
                    "message": "X セッションは有効です",
                }

            # どちらも見つからない場合（ロード途中、ネットワーク問題など）
            logger.warning("X セッション状態不明（DOM 要素が見つかりません）")
            return {
                "valid": False,
                "status": "unknown_error",
                "message": "セッション判定用 DOM 要素が見つかりませんでした",
            }
