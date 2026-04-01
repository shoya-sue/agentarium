"""
tests/test_reply_x.py — ReplyXSkill ユニットテスト

X (Twitter) への返信投稿 Skill の意思決定ロジックを検証する。
dry_run モードで実際のブラウザを起動せずにロジックをテストする。
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestReplyXSkillImport:
    """インポートとクラス構造の確認"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.action.reply_x import ReplyXSkill
        assert ReplyXSkill is not None

    def test_instantiate(self):
        """インスタンス化できる"""
        from skills.action.reply_x import ReplyXSkill
        skill = ReplyXSkill()
        assert skill is not None

    def test_has_run_method(self):
        """run メソッドが存在する"""
        from skills.action.reply_x import ReplyXSkill
        skill = ReplyXSkill()
        assert callable(skill.run)

    def test_max_reply_length_constant(self):
        """MAX_REPLY_LENGTH 定数が 280 である"""
        from skills.action.reply_x import MAX_REPLY_LENGTH
        assert MAX_REPLY_LENGTH == 280


class TestReplyXSkillDryRun:
    """dry_run モードの検証（ブラウザ不要）"""

    def test_dry_run_returns_false_posted(self):
        """dry_run=True のとき posted が False である"""
        from skills.action.reply_x import ReplyXSkill
        skill = ReplyXSkill()
        result = asyncio.run(
            skill.run({
                "tweet_url": "https://x.com/user/status/123456789",
                "text": "Great post!",
                "dry_run": True,
            })
        )
        assert result["posted"] is False

    def test_dry_run_returns_dry_run_true(self):
        """dry_run=True のとき dry_run フラグが True である"""
        from skills.action.reply_x import ReplyXSkill
        skill = ReplyXSkill()
        result = asyncio.run(
            skill.run({
                "tweet_url": "https://x.com/user/status/123456789",
                "text": "Great post!",
                "dry_run": True,
            })
        )
        assert result["dry_run"] is True

    def test_dry_run_returns_reason_dry_run(self):
        """dry_run=True のとき reason が dry_run である"""
        from skills.action.reply_x import ReplyXSkill
        skill = ReplyXSkill()
        result = asyncio.run(
            skill.run({
                "tweet_url": "https://x.com/user/status/123456789",
                "text": "Great post!",
                "dry_run": True,
            })
        )
        assert result["reason"] == "dry_run"

    def test_dry_run_returns_text_length(self):
        """dry_run=True のとき text_length が返される"""
        from skills.action.reply_x import ReplyXSkill
        skill = ReplyXSkill()
        text = "Great post!"
        result = asyncio.run(
            skill.run({
                "tweet_url": "https://x.com/user/status/123456789",
                "text": text,
                "dry_run": True,
            })
        )
        assert result["text_length"] == len(text)


class TestReplyXSkillOutputSchema:
    """出力スキーマの検証"""

    def test_output_has_required_fields(self):
        """出力に必須フィールドが含まれる"""
        from skills.action.reply_x import ReplyXSkill
        skill = ReplyXSkill()
        result = asyncio.run(
            skill.run({
                "tweet_url": "https://x.com/user/status/123456789",
                "text": "Great post!",
                "dry_run": True,
            })
        )
        assert "posted" in result
        assert "text" in result
        assert "text_length" in result
        assert "dry_run" in result
        assert "tweet_url" in result

    def test_tweet_url_is_echoed_back(self):
        """入力 tweet_url が出力にエコーバックされる"""
        from skills.action.reply_x import ReplyXSkill
        skill = ReplyXSkill()
        url = "https://x.com/user/status/123456789"
        result = asyncio.run(
            skill.run({"tweet_url": url, "text": "Hello!", "dry_run": True})
        )
        assert result["tweet_url"] == url

    def test_posted_is_bool(self):
        """posted フィールドが bool 型である"""
        from skills.action.reply_x import ReplyXSkill
        skill = ReplyXSkill()
        result = asyncio.run(
            skill.run({
                "tweet_url": "https://x.com/user/status/123456789",
                "text": "Hello!",
                "dry_run": True,
            })
        )
        assert isinstance(result["posted"], bool)


class TestReplyXSkillValidation:
    """入力バリデーションの検証"""

    def test_empty_text_returns_not_posted(self):
        """空のテキストは返信しない"""
        from skills.action.reply_x import ReplyXSkill
        skill = ReplyXSkill()
        result = asyncio.run(
            skill.run({
                "tweet_url": "https://x.com/user/status/123456789",
                "text": "",
                "dry_run": True,
            })
        )
        assert result["posted"] is False
        assert result["reason"] == "empty_text"

    def test_missing_tweet_url_returns_not_posted(self):
        """tweet_url が None のとき返信しない"""
        from skills.action.reply_x import ReplyXSkill
        skill = ReplyXSkill()
        result = asyncio.run(
            skill.run({
                "tweet_url": None,
                "text": "Hello!",
                "dry_run": True,
            })
        )
        assert result["posted"] is False
        assert result["reason"] == "missing_tweet_url"

    def test_text_exactly_280_chars_is_valid(self):
        """280 文字ちょうどは有効"""
        from skills.action.reply_x import ReplyXSkill, MAX_REPLY_LENGTH
        skill = ReplyXSkill()
        text = "a" * MAX_REPLY_LENGTH
        result = asyncio.run(
            skill.run({
                "tweet_url": "https://x.com/user/status/123456789",
                "text": text,
                "dry_run": True,
            })
        )
        assert result.get("reason") != "text_too_long"

    def test_text_281_chars_is_invalid(self):
        """281 文字は無効"""
        from skills.action.reply_x import ReplyXSkill, MAX_REPLY_LENGTH
        skill = ReplyXSkill()
        text = "a" * (MAX_REPLY_LENGTH + 1)
        result = asyncio.run(
            skill.run({
                "tweet_url": "https://x.com/user/status/123456789",
                "text": text,
                "dry_run": True,
            })
        )
        assert result["posted"] is False
        assert result["reason"] == "text_too_long"

    def test_invalid_tweet_url_format_returns_not_posted(self):
        """X の URL 形式ではない場合は返信しない"""
        from skills.action.reply_x import ReplyXSkill
        skill = ReplyXSkill()
        result = asyncio.run(
            skill.run({
                "tweet_url": "https://example.com/not-a-tweet",
                "text": "Hello!",
                "dry_run": True,
            })
        )
        assert result["posted"] is False
        assert result["reason"] == "invalid_tweet_url"


class TestReplyXSkillBrowserMock:
    """モック Playwright を使ったブラウザ返信ロジックの検証"""

    def test_browser_reply_success(self):
        """ブラウザ返信が成功すると posted=True が返る"""
        from skills.action.reply_x import ReplyXSkill
        skill = ReplyXSkill()

        mock_page = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=MagicMock())
        mock_page.click = AsyncMock()
        mock_page.fill = AsyncMock()
        mock_page.wait_for_selector = AsyncMock(return_value=MagicMock())

        async def run_with_mock():
            return await skill._post_reply(
                mock_page, "https://x.com/user/status/123456789", "Great post!"
            )

        result = asyncio.run(run_with_mock())
        assert result["posted"] is True

    def test_browser_reply_failure_returns_false(self):
        """ブラウザ返信でエラーが発生した場合 posted=False が返る"""
        from skills.action.reply_x import ReplyXSkill
        skill = ReplyXSkill()

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(side_effect=Exception("Network error"))

        async def run_with_mock():
            return await skill._post_reply(
                mock_page, "https://x.com/user/status/123456789", "Great post!"
            )

        result = asyncio.run(run_with_mock())
        assert result["posted"] is False
