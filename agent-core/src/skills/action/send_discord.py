"""
skills/action/send_discord.py — Discord Webhook 送信 Skill

Discord Webhook を通じてメッセージを送信する。
httpx.AsyncClient を使用した非同期 POST。

Webhook URL はセキュリティのためログに出力しない（masked のみ表示）。

Skill 入出力スキーマ: config/skills/action/send_discord.yaml
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import httpx
import yaml

logger = logging.getLogger(__name__)

# Discord メッセージの最大文字数
_MAX_MESSAGE_LENGTH: int = 2000

# 末尾省略記号
_TRUNCATION_SUFFIX: str = "..."

# HTTP タイムアウト（秒）
_HTTP_TIMEOUT: float = 10.0

# Webhook URL の環境変数名
_ENV_WEBHOOK_URL: str = "DISCORD_WEBHOOK_URL"


def _load_settings(config_dir: Path) -> dict[str, Any]:
    """
    config/settings.yaml を読み込む。
    ファイルが存在しない場合は空 dict を返す。
    """
    settings_path = config_dir / "settings.yaml"
    if not settings_path.exists():
        logger.warning("settings.yaml が見つかりません: %s", settings_path)
        return {}
    with settings_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _resolve_webhook_url(
    webhook_url_param: str | None,
    settings: dict[str, Any],
) -> str | None:
    """
    Webhook URL を解決する。優先順位:
    1. params の webhook_url
    2. 環境変数 DISCORD_WEBHOOK_URL
    3. settings.yaml の discord.webhook_url

    Returns:
        解決された Webhook URL、または None
    """
    # 1. params 直接指定
    if webhook_url_param:
        return webhook_url_param

    # 2. 環境変数
    env_url = os.environ.get(_ENV_WEBHOOK_URL, "")
    if env_url:
        return env_url

    # 3. settings.yaml
    discord_cfg = settings.get("discord", {})
    settings_url = discord_cfg.get("webhook_url", "")
    if settings_url:
        return settings_url

    return None


def _mask_webhook_url(url: str) -> str:
    """
    Webhook URL の末尾 20 文字のみ表示するマスク処理。
    セキュリティのため URL 全体をログに出力しない。
    """
    if len(url) <= 20:
        return url[-20:]
    return "..." + url[-20:]


def _truncate_message(message: str, max_length: int) -> str:
    """
    メッセージを最大文字数に切り詰める。
    超過した場合は末尾に "..." を付加する。

    Args:
        message: 元のメッセージ
        max_length: 最大文字数

    Returns:
        切り詰め後のメッセージ
    """
    if len(message) <= max_length:
        return message
    # 末尾に "..." を付加するため、その分を差し引いた位置で切る
    cut_pos = max_length - len(_TRUNCATION_SUFFIX)
    return message[:cut_pos] + _TRUNCATION_SUFFIX


class SendDiscordSkill:
    """
    send_discord Skill の実装。

    Discord Webhook を通じてメッセージを送信する。
    空メッセージはスキップ、レート制限時は1回リトライ。
    """

    def __init__(self, config_dir: Path | str | None = None) -> None:
        if config_dir is None:
            config_dir = Path(__file__).parent.parent.parent.parent.parent / "config"
        self._config_dir = Path(config_dir)
        self._settings = _load_settings(self._config_dir)

    def _get_default_username(self) -> str:
        """settings.yaml から default_username を取得する。"""
        discord_cfg = self._settings.get("discord", {})
        return discord_cfg.get("default_username", "Agentarium")

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Discord Webhook にメッセージを送信する。

        Args:
            params:
                message (str): 送信するメッセージ本文（必須）
                username (str | None): Webhookの表示名
                avatar_url (str | None): アバター画像URL
                webhook_url (str | None): 送信先 Webhook URL

        Returns:
            {
                "sent": bool,               # 送信成功フラグ
                "status_code": int,         # HTTP ステータスコード
                "message_length": int,      # 実際に送信した文字数
                "webhook_url_masked": str,  # URL の末尾20文字のみ
            }

        Raises:
            ValueError: webhook_url が設定されていない場合
        """
        message: str = params["message"]
        username: str | None = params.get("username")
        avatar_url: str | None = params.get("avatar_url")
        webhook_url_param: str | None = params.get("webhook_url")

        # Webhook URL の解決
        webhook_url = _resolve_webhook_url(webhook_url_param, self._settings)
        if not webhook_url:
            raise ValueError(
                "Discord Webhook URL が設定されていません。"
                f"環境変数 {_ENV_WEBHOOK_URL} または config/settings.yaml の "
                "discord.webhook_url を設定してください。"
            )

        # マスクされた URL（ログ用）
        masked_url = _mask_webhook_url(webhook_url)

        # 空メッセージはスキップ
        if not message:
            logger.info("send_discord: 空メッセージのため送信をスキップ: masked_url=%s", masked_url)
            return {
                "sent": False,
                "status_code": 0,
                "message_length": 0,
                "webhook_url_masked": masked_url,
                "reason": "empty_message",
            }

        # メッセージの文字数制限処理
        truncated_message = _truncate_message(message, _MAX_MESSAGE_LENGTH)
        if len(truncated_message) < len(message):
            logger.info(
                "send_discord: メッセージを %d 文字に切り詰め（元: %d 文字）",
                len(truncated_message),
                len(message),
            )

        # Webhook ペイロード組み立て（immutable dict として構築）
        payload: dict[str, Any] = {"content": truncated_message}
        if username:
            payload = {**payload, "username": username}
        elif self._get_default_username():
            payload = {**payload, "username": self._get_default_username()}
        if avatar_url:
            payload = {**payload, "avatar_url": avatar_url}

        # HTTP POST（非同期）
        return await self._post_with_retry(
            webhook_url=webhook_url,
            payload=payload,
            masked_url=masked_url,
            message_length=len(truncated_message),
        )

    async def _post_with_retry(
        self,
        webhook_url: str,
        payload: dict[str, Any],
        masked_url: str,
        message_length: int,
    ) -> dict[str, Any]:
        """
        Webhook に POST し、429 の場合は1回リトライする。

        Args:
            webhook_url: 送信先 URL
            payload: リクエストボディ
            masked_url: ログ用マスク済み URL
            message_length: 送信メッセージ文字数

        Returns:
            送信結果 dict
        """
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            try:
                response = await client.post(webhook_url, json=payload)

                # レート制限（429）: retry_after 秒待機して1回リトライ
                if response.status_code == 429:
                    retry_after: float = 1.0
                    try:
                        retry_after = float(response.json().get("retry_after", 1.0))
                    except Exception:
                        pass
                    logger.warning(
                        "send_discord: レート制限 (429)。%.1f 秒後にリトライ: masked_url=%s",
                        retry_after,
                        masked_url,
                    )
                    await asyncio.sleep(retry_after)
                    response = await client.post(webhook_url, json=payload)

                # 成功判定（204 No Content or 200 OK）
                if response.status_code in (200, 204):
                    logger.info(
                        "send_discord: 送信成功 status=%d length=%d masked_url=%s",
                        response.status_code,
                        message_length,
                        masked_url,
                    )
                    return {
                        "sent": True,
                        "status_code": response.status_code,
                        "message_length": message_length,
                        "webhook_url_masked": masked_url,
                    }

                # HTTP エラー（4xx/5xx, 429 除く）
                logger.warning(
                    "send_discord: HTTP エラー status=%d masked_url=%s",
                    response.status_code,
                    masked_url,
                )
                return {
                    "sent": False,
                    "status_code": response.status_code,
                    "message_length": message_length,
                    "webhook_url_masked": masked_url,
                }

            except httpx.TimeoutException as exc:
                logger.error("send_discord: タイムアウトエラー: %s masked_url=%s", exc, masked_url)
                return {
                    "sent": False,
                    "status_code": 0,
                    "message_length": message_length,
                    "webhook_url_masked": masked_url,
                }
            except httpx.RequestError as exc:
                logger.error("send_discord: ネットワークエラー: %s masked_url=%s", exc, masked_url)
                return {
                    "sent": False,
                    "status_code": 0,
                    "message_length": message_length,
                    "webhook_url_masked": masked_url,
                }
