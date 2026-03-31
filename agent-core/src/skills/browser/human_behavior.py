"""
skills/browser/human_behavior.py — ヒューマナイズブラウザ操作 Skill

人間らしいブラウザ操作（ランダム遅延・スクロール・マウス移動）を
Playwright ページオブジェクトに注入する。

bot 検出回避のための「人間的な揺らぎ」を付与する Phase 1 の基盤 Skill。
X 操作時は safety_x.yaml の delay も追加で適用する。

Skill 入出力スキーマ: config/skills/browser/human_behavior.yaml
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

logger = logging.getLogger(__name__)


class HumanBehaviorSkill:
    """
    human_behavior Skill の実装。

    Playwright の Page オブジェクトを受け取り、
    人間的な操作（ランダム遅延、スクロール、マウス移動）を実行する。

    Phase 1: pause_range / scroll_step はハードコード。
             Phase 2 以降で config/browser/stealth.yaml と連動予定。
    """

    # ランダム遅延範囲（ミリ秒）— human_behavior.yaml の behavior.pause_range_ms
    _PAUSE_RANGE_MS: tuple[int, int] = (500, 3000)

    # スクロール量範囲（px/step）— human_behavior.yaml の behavior.scroll_step_range
    _SCROLL_STEP_RANGE: tuple[int, int] = (50, 200)

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        ヒューマナイズアクションを実行する。

        Args:
            params:
                action (str): 実行アクション
                    "scroll"           — ページをスクロール
                    "mouse_move"       — マウスをランダム移動
                    "random_pause"     — ランダム時間待機
                    "click_with_delay" — 遅延付きクリック
                page: Playwright Page オブジェクト（必須、action に応じて使用）
                target_selector (str | None): クリック対象セレクタ（click_with_delay 時）
                scroll_direction (str): "down" | "up"（scroll 時）
                scroll_distance_px (int | None): スクロール量（省略時はランダム）

        Returns:
            {"success": bool, "duration_ms": int, "action_performed": str}
        """
        action: str = params["action"]
        page = params.get("page")

        start_ms = time.monotonic() * 1000

        try:
            if action == "random_pause":
                duration_ms = await self._random_pause()
                action_performed = f"random_pause ({duration_ms}ms)"

            elif action == "scroll":
                if page is None:
                    raise ValueError("scroll アクションには page が必要です")
                direction = params.get("scroll_direction", "down")
                distance = params.get("scroll_distance_px") or random.randint(
                    *self._SCROLL_STEP_RANGE
                )
                await self._scroll(page, direction=direction, distance_px=distance)
                action_performed = f"scroll_{direction} ({distance}px)"

            elif action == "mouse_move":
                if page is None:
                    raise ValueError("mouse_move アクションには page が必要です")
                await self._mouse_move(page)
                action_performed = "mouse_move"

            elif action == "click_with_delay":
                if page is None:
                    raise ValueError("click_with_delay アクションには page が必要です")
                selector = params.get("target_selector")
                if not selector:
                    raise ValueError("click_with_delay には target_selector が必要です")
                await self._click_with_delay(page, selector)
                action_performed = f"click_with_delay ({selector})"

            else:
                raise ValueError(
                    f"未対応のアクション: '{action}'. "
                    f"対応アクション: scroll / mouse_move / random_pause / click_with_delay"
                )

        except Exception as exc:
            elapsed_ms = int(time.monotonic() * 1000 - start_ms)
            logger.warning("human_behavior エラー: action=%s error=%s", action, exc)
            return {
                "success": False,
                "duration_ms": elapsed_ms,
                "action_performed": action,
            }

        elapsed_ms = int(time.monotonic() * 1000 - start_ms)
        logger.debug("human_behavior: %s (%dms)", action_performed, elapsed_ms)

        return {
            "success": True,
            "duration_ms": elapsed_ms,
            "action_performed": action_performed,
        }

    async def _random_pause(self) -> int:
        """ランダムな時間だけ待機する。待機した ms を返す。"""
        ms = random.randint(*self._PAUSE_RANGE_MS)
        await asyncio.sleep(ms / 1000)
        return ms

    async def _scroll(self, page: Any, direction: str, distance_px: int) -> None:
        """
        ページをスクロールする。

        Playwright の mouse.wheel を使用（CDP スクロールより自然）。
        """
        # スクロールをステップ分割して自然な速度に見せる
        steps = random.randint(3, 8)
        step_px = distance_px // steps

        for _ in range(steps):
            delta_y = step_px if direction == "down" else -step_px
            await page.mouse.wheel(0, delta_y)
            # ステップ間にランダム遅延（50〜200ms）
            await asyncio.sleep(random.uniform(0.05, 0.2))

    async def _mouse_move(self, page: Any) -> None:
        """
        マウスをランダムな座標に移動する。

        ベジェ曲線的な動きの近似として中間点を経由する。
        """
        viewport = page.viewport_size or {"width": 1280, "height": 720}
        width = viewport.get("width", 1280)
        height = viewport.get("height", 720)

        # ランダムな目標座標
        target_x = random.randint(100, width - 100)
        target_y = random.randint(100, height - 100)

        # 中間点を 2〜4 点経由して移動
        steps = random.randint(2, 4)
        for i in range(1, steps + 1):
            # 直線補間 + ランダム揺らぎ
            t = i / steps
            mid_x = int(target_x * t + random.randint(-30, 30))
            mid_y = int(target_y * t + random.randint(-30, 30))
            # 画面内にクリップ
            mid_x = max(0, min(width, mid_x))
            mid_y = max(0, min(height, mid_y))
            await page.mouse.move(mid_x, mid_y)
            await asyncio.sleep(random.uniform(0.02, 0.08))

    async def _click_with_delay(self, page: Any, selector: str) -> None:
        """
        セレクタが示す要素を遅延付きでクリックする。

        クリック前後にランダム待機を挟んで人間らしい操作を模倣する。
        """
        # クリック前の短い停留
        await asyncio.sleep(random.uniform(0.3, 1.0))

        element = await page.query_selector(selector)
        if element is None:
            raise ValueError(f"クリック対象が見つかりません: {selector}")

        # マウスを要素に移動してからクリック（自然なホバー動作）
        bounding_box = await element.bounding_box()
        if bounding_box:
            center_x = bounding_box["x"] + bounding_box["width"] / 2
            center_y = bounding_box["y"] + bounding_box["height"] / 2
            await page.mouse.move(center_x, center_y)
            await asyncio.sleep(random.uniform(0.1, 0.4))

        await element.click()

        # クリック後の短い停留
        await asyncio.sleep(random.uniform(0.2, 0.8))
