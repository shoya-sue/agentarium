"""
tests/test_post_x.py — PostXSkill ユニットテスト

X (Twitter) への投稿 Skill の意思決定ロジックを検証する。
dry_run モードで実際のブラウザを起動せずにロジックをテストする。
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestPostXSkillImport:
    """インポートとクラス構造の確認"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.action.post_x import PostXSkill
        assert PostXSkill is not None

    def test_instantiate(self):
        """インスタンス化できる"""
        from skills.action.post_x import PostXSkill
        skill = PostXSkill()
        assert skill is not None

    def test_has_run_method(self):
        """run メソッドが存在する"""
        from skills.action.post_x import PostXSkill
        skill = PostXSkill()
        assert callable(skill.run)

    def test_max_tweet_length_constant(self):
        """MAX_TWEET_LENGTH 定数が 280 である"""
        from skills.action.post_x import MAX_TWEET_LENGTH
        assert MAX_TWEET_LENGTH == 280


class TestPostXSkillDryRun:
    """dry_run モードの検証（ブラウザ不要）"""

    def test_dry_run_returns_false_posted(self):
        """dry_run=True のとき posted が False である"""
        from skills.action.post_x import PostXSkill
        skill = PostXSkill()
        result = asyncio.run(
            skill.run({"text": "Hello world!", "dry_run": True})
        )
        assert result["posted"] is False

    def test_dry_run_returns_dry_run_true(self):
        """dry_run=True のとき出力に dry_run フラグが含まれる"""
        from skills.action.post_x import PostXSkill
        skill = PostXSkill()
        result = asyncio.run(
            skill.run({"text": "Hello world!", "dry_run": True})
        )
        assert result["dry_run"] is True

    def test_dry_run_returns_text_length(self):
        """dry_run=True のとき text_length が返される"""
        from skills.action.post_x import PostXSkill
        skill = PostXSkill()
        text = "Hello world!"
        result = asyncio.run(
            skill.run({"text": text, "dry_run": True})
        )
        assert result["text_length"] == len(text)

    def test_dry_run_returns_reason_dry_run(self):
        """dry_run=True のとき reason が dry_run である"""
        from skills.action.post_x import PostXSkill
        skill = PostXSkill()
        result = asyncio.run(
            skill.run({"text": "Hello world!", "dry_run": True})
        )
        assert result["reason"] == "dry_run"


class TestPostXSkillOutputSchema:
    """出力スキーマの検証"""

    def test_output_has_required_fields(self):
        """出力に必須フィールドが含まれる"""
        from skills.action.post_x import PostXSkill
        skill = PostXSkill()
        result = asyncio.run(
            skill.run({"text": "Hello world!", "dry_run": True})
        )
        assert "posted" in result
        assert "text" in result
        assert "text_length" in result
        assert "dry_run" in result

    def test_posted_is_bool(self):
        """posted フィールドが bool 型である"""
        from skills.action.post_x import PostXSkill
        skill = PostXSkill()
        result = asyncio.run(
            skill.run({"text": "Hello world!", "dry_run": True})
        )
        assert isinstance(result["posted"], bool)

    def test_text_length_is_int(self):
        """text_length が int 型である"""
        from skills.action.post_x import PostXSkill
        skill = PostXSkill()
        result = asyncio.run(
            skill.run({"text": "Hello world!", "dry_run": True})
        )
        assert isinstance(result["text_length"], int)


class TestPostXSkillValidation:
    """入力バリデーションの検証"""

    def test_empty_text_returns_not_posted(self):
        """空のテキストは投稿しない"""
        from skills.action.post_x import PostXSkill
        skill = PostXSkill()
        result = asyncio.run(
            skill.run({"text": "", "dry_run": True})
        )
        assert result["posted"] is False
        assert result["reason"] == "empty_text"

    def test_text_exactly_280_chars_is_valid(self):
        """280 文字ちょうどは有効"""
        from skills.action.post_x import PostXSkill, MAX_TWEET_LENGTH
        skill = PostXSkill()
        text = "a" * MAX_TWEET_LENGTH
        result = asyncio.run(
            skill.run({"text": text, "dry_run": True})
        )
        # dry_run のため posted=False だが reason は text_too_long でない
        assert result.get("reason") != "text_too_long"

    def test_text_281_chars_is_invalid(self):
        """281 文字は無効"""
        from skills.action.post_x import PostXSkill, MAX_TWEET_LENGTH
        skill = PostXSkill()
        text = "a" * (MAX_TWEET_LENGTH + 1)
        result = asyncio.run(
            skill.run({"text": text, "dry_run": True})
        )
        assert result["posted"] is False
        assert result["reason"] == "text_too_long"

    def test_text_too_long_returns_text_length(self):
        """281 文字以上のとき text_length が実際の長さを返す"""
        from skills.action.post_x import PostXSkill, MAX_TWEET_LENGTH
        skill = PostXSkill()
        text = "a" * (MAX_TWEET_LENGTH + 50)
        result = asyncio.run(
            skill.run({"text": text, "dry_run": True})
        )
        assert result["text_length"] == len(text)


class TestPostXSkillBrowserMock:
    """モック Playwright を使ったブラウザ投稿ロジックの検証"""

    def test_browser_post_success(self):
        """ブラウザ投稿が成功すると posted=True が返る"""
        from skills.action.post_x import PostXSkill
        skill = PostXSkill()

        mock_page = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=MagicMock())
        mock_page.click = AsyncMock()
        mock_page.fill = AsyncMock()
        mock_page.keyboard.press = AsyncMock()
        mock_page.wait_for_selector = AsyncMock(return_value=MagicMock())

        async def run_with_mock():
            return await skill._post_tweet(mock_page, "Hello world!")

        result = asyncio.run(run_with_mock())
        assert result["posted"] is True

    def test_browser_post_failure_returns_false(self):
        """ブラウザ投稿でエラーが発生した場合 posted=False が返る"""
        from skills.action.post_x import PostXSkill
        skill = PostXSkill()

        mock_page = AsyncMock()
        mock_page.query_selector = AsyncMock(side_effect=Exception("Browser error"))

        async def run_with_mock():
            return await skill._post_tweet(mock_page, "Hello world!")

        result = asyncio.run(run_with_mock())
        assert result["posted"] is False
