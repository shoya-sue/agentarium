"""
tests/test_send_discord.py — SendDiscordSkill ユニットテスト

httpx.AsyncClient をモックして Discord Webhook 送信ロジックを検証する。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# テスト用の Webhook URL（実際には使用しない）
_DUMMY_WEBHOOK_URL = "https://discord.com/api/webhooks/123456789/abcdefghij1234567890"


def _make_mock_response(status_code: int, json_data: Optional[dict] = None) -> MagicMock:
    """httpx.Response のモックを作成する。"""
    mock = MagicMock()
    mock.status_code = status_code
    if json_data is not None:
        mock.json = MagicMock(return_value=json_data)
    else:
        mock.json = MagicMock(return_value={})
    return mock


class TestSendDiscordSkill:
    """SendDiscordSkill の動作検証"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.action.send_discord import SendDiscordSkill
        assert SendDiscordSkill is not None

    @pytest.mark.asyncio
    async def test_sends_message_successfully(self):
        """httpx をモック → status 204 → sent=True"""
        from skills.action.send_discord import SendDiscordSkill

        mock_response = _make_mock_response(204)

        with patch("httpx.AsyncClient") as mock_client_cls:
            # AsyncClient.__aenter__ が返すクライアントのモック
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            skill = SendDiscordSkill()
            result = await skill.run({
                "message": "テストメッセージ",
                "webhook_url": _DUMMY_WEBHOOK_URL,
            })

        assert result["sent"] is True
        assert result["status_code"] == 204

    @pytest.mark.asyncio
    async def test_empty_message_not_sent(self):
        """message='' → sent=False, reason='empty_message'"""
        from skills.action.send_discord import SendDiscordSkill

        skill = SendDiscordSkill()
        result = await skill.run({
            "message": "",
            "webhook_url": _DUMMY_WEBHOOK_URL,
        })

        assert result["sent"] is False
        assert result.get("reason") == "empty_message"

    @pytest.mark.asyncio
    async def test_message_truncated_at_2000_chars(self):
        """2001文字メッセージ → 2000文字にトリミング"""
        from skills.action.send_discord import SendDiscordSkill

        long_message = "a" * 2001
        mock_response = _make_mock_response(204)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            skill = SendDiscordSkill()
            result = await skill.run({
                "message": long_message,
                "webhook_url": _DUMMY_WEBHOOK_URL,
            })

        # 2000文字以内に切り詰められている
        assert result["message_length"] <= 2000
        assert result["sent"] is True

        # 実際に POST されたペイロードを確認
        call_args = mock_client.post.call_args
        sent_content = call_args.kwargs.get("json", {}).get("content", "")
        assert len(sent_content) <= 2000

    @pytest.mark.asyncio
    async def test_raises_on_missing_webhook_url(self):
        """webhook_url なし → ValueError を raise する"""
        from skills.action.send_discord import SendDiscordSkill

        # 環境変数もクリア
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISCORD_WEBHOOK_URL", None)
            skill = SendDiscordSkill()

            with pytest.raises(ValueError):
                await skill.run({"message": "テストメッセージ"})

    @pytest.mark.asyncio
    async def test_webhook_url_masked_in_result(self):
        """webhook_url_masked は末尾20文字のみ"""
        from skills.action.send_discord import SendDiscordSkill

        mock_response = _make_mock_response(204)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            skill = SendDiscordSkill()
            result = await skill.run({
                "message": "テストメッセージ",
                "webhook_url": _DUMMY_WEBHOOK_URL,
            })

        # masked は "..." + 末尾20文字
        masked = result["webhook_url_masked"]
        assert _DUMMY_WEBHOOK_URL[-20:] in masked
        # URL の先頭部分（トークン等）は含まれない
        assert "https://discord.com/api/webhooks/" not in masked

    @pytest.mark.asyncio
    async def test_http_error_returns_not_sent(self):
        """status 500 → sent=False"""
        from skills.action.send_discord import SendDiscordSkill

        mock_response = _make_mock_response(500)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            skill = SendDiscordSkill()
            result = await skill.run({
                "message": "テストメッセージ",
                "webhook_url": _DUMMY_WEBHOOK_URL,
            })

        assert result["sent"] is False
        assert result["status_code"] == 500

    @pytest.mark.asyncio
    async def test_uses_env_webhook_url(self):
        """DISCORD_WEBHOOK_URL 環境変数から URL を読む"""
        from skills.action.send_discord import SendDiscordSkill

        env_webhook_url = "https://discord.com/api/webhooks/env_test/env_token_1234567890"
        mock_response = _make_mock_response(204)

        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": env_webhook_url}):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

                skill = SendDiscordSkill()
                result = await skill.run({"message": "環境変数テスト"})

        assert result["sent"] is True
        # 環境変数 URL の末尾が masked に含まれる
        assert env_webhook_url[-20:] in result["webhook_url_masked"]

    @pytest.mark.asyncio
    async def test_network_error_returns_status_zero(self):
        """ネットワークエラー → sent=False, status_code=0"""
        import httpx
        from skills.action.send_discord import SendDiscordSkill

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=httpx.RequestError("接続失敗", request=MagicMock())
            )
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            skill = SendDiscordSkill()
            result = await skill.run({
                "message": "テストメッセージ",
                "webhook_url": _DUMMY_WEBHOOK_URL,
            })

        assert result["sent"] is False
        assert result["status_code"] == 0
