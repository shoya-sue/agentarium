"""
tests/test_human_behavior.py — HumanBehaviorSkill ユニットテスト

Playwright の Page オブジェクトをモックして動作を検証する。
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _make_mock_page(width: int = 1280, height: int = 720) -> MagicMock:
    """Playwright Page のモックを作成する。"""
    page = MagicMock()
    page.viewport_size = {"width": width, "height": height}
    page.mouse = MagicMock()
    page.mouse.wheel = AsyncMock()
    page.mouse.move = AsyncMock()

    element = MagicMock()
    element.bounding_box = AsyncMock(return_value={
        "x": 100, "y": 200, "width": 50, "height": 30
    })
    element.click = AsyncMock()

    page.query_selector = AsyncMock(return_value=element)
    return page


class TestHumanBehaviorSkill:
    """HumanBehaviorSkill の動作検証"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.browser.human_behavior import HumanBehaviorSkill
        assert HumanBehaviorSkill is not None

    @pytest.mark.asyncio
    async def test_random_pause_returns_success(self):
        """random_pause アクションが成功を返す"""
        from skills.browser.human_behavior import HumanBehaviorSkill
        skill = HumanBehaviorSkill()
        result = await skill.run({"action": "random_pause"})
        assert result["success"] is True
        assert result["action_performed"].startswith("random_pause")
        assert result["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_scroll_down_calls_mouse_wheel(self):
        """scroll down アクションが mouse.wheel を呼び出す"""
        from skills.browser.human_behavior import HumanBehaviorSkill
        skill = HumanBehaviorSkill()
        page = _make_mock_page()

        result = await skill.run({
            "action": "scroll",
            "page": page,
            "scroll_direction": "down",
            "scroll_distance_px": 100,
        })

        assert result["success"] is True
        assert "scroll_down" in result["action_performed"]
        # mouse.wheel が少なくとも1回呼ばれている
        assert page.mouse.wheel.call_count >= 1

    @pytest.mark.asyncio
    async def test_scroll_up_uses_negative_delta(self):
        """scroll up アクションが負の delta_y を使用する"""
        from skills.browser.human_behavior import HumanBehaviorSkill
        skill = HumanBehaviorSkill()
        page = _make_mock_page()

        await skill.run({
            "action": "scroll",
            "page": page,
            "scroll_direction": "up",
            "scroll_distance_px": 100,
        })

        # 全コールで y が負（上スクロール）
        for call in page.mouse.wheel.call_args_list:
            _, kwargs = call
            # wheel(0, delta_y) の形式
            args = call[0]
            delta_y = args[1] if len(args) > 1 else kwargs.get("delta_y", 0)
            assert delta_y < 0

    @pytest.mark.asyncio
    async def test_mouse_move_calls_mouse_move(self):
        """mouse_move アクションが page.mouse.move を呼び出す"""
        from skills.browser.human_behavior import HumanBehaviorSkill
        skill = HumanBehaviorSkill()
        page = _make_mock_page()

        result = await skill.run({
            "action": "mouse_move",
            "page": page,
        })

        assert result["success"] is True
        assert page.mouse.move.call_count >= 1

    @pytest.mark.asyncio
    async def test_click_with_delay_clicks_element(self):
        """click_with_delay アクションが要素をクリックする"""
        from skills.browser.human_behavior import HumanBehaviorSkill
        skill = HumanBehaviorSkill()
        page = _make_mock_page()

        result = await skill.run({
            "action": "click_with_delay",
            "page": page,
            "target_selector": "[data-testid='submit']",
        })

        assert result["success"] is True
        page.query_selector.assert_called_once_with("[data-testid='submit']")

    @pytest.mark.asyncio
    async def test_click_with_delay_element_not_found(self):
        """クリック対象が見つからない場合は success: False を返す"""
        from skills.browser.human_behavior import HumanBehaviorSkill
        skill = HumanBehaviorSkill()
        page = _make_mock_page()
        page.query_selector = AsyncMock(return_value=None)

        result = await skill.run({
            "action": "click_with_delay",
            "page": page,
            "target_selector": "[data-testid='missing']",
        })

        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_scroll_requires_page(self):
        """scroll アクションに page がない場合は success: False を返す"""
        from skills.browser.human_behavior import HumanBehaviorSkill
        skill = HumanBehaviorSkill()

        result = await skill.run({"action": "scroll"})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_unknown_action_returns_failure(self):
        """未知のアクションは success: False を返す"""
        from skills.browser.human_behavior import HumanBehaviorSkill
        skill = HumanBehaviorSkill()

        result = await skill.run({"action": "unknown_action"})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_result_contains_duration_ms(self):
        """結果に duration_ms フィールドが含まれる"""
        from skills.browser.human_behavior import HumanBehaviorSkill
        skill = HumanBehaviorSkill()
        result = await skill.run({"action": "random_pause"})
        assert "duration_ms" in result
        assert isinstance(result["duration_ms"], int)
