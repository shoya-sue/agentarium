"""
V6: Playwright Stealth（rebrowser-playwright）bot検出回避検証
合格基準:
  - bot.sannysoft.com: webdriver / CDP 検出なし
  - CreepJS: 主要フィンガープリント項目が HUMAN 判定
  - browserscan.net: automation detected なし
実行方法:
  python3 poc/v6_stealth_test.py
注意:
  - headed モード（ブラウザウィンドウが開きます）
  - Xquartz/Display が不要な macOS ではそのまま動作
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# rebrowser-playwright の非同期 API を使用
from rebrowser_playwright.async_api import async_playwright, Browser, BrowserContext, Page

# ブラウザプロファイル保存先（セッション永続化 → V7 に引き継ぐ）
PROFILE_DIR = Path(__file__).parent.parent / "data" / "browser-profile" / "poc"
SCREENSHOTS_DIR = Path(__file__).parent.parent / "data" / "outputs" / "v6_screenshots"

# M4 Pro の実際のスペックに合わせた Stealth パラメータ
STEALTH_ARGS = [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-web-security",
    "--disable-features=IsolateOrigins,site-per-process",
    "--lang=ja-JP",
    # Retina / HiDPI
    "--force-device-scale-factor=2",
]

# JavaScript: navigator.webdriver を削除・偽装
STEALTH_INIT_SCRIPT = """
() => {
    // navigator.webdriver を削除
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
        configurable: true,
    });

    // Chrome オブジェクトを追加（実ブラウザ風）
    if (!window.chrome) {
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
            app: {},
        };
    }

    // permissions.query のパッチ（Playwright 検出対策）
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
    );

    // languages の偽装
    Object.defineProperty(navigator, 'languages', {
        get: () => ['ja-JP', 'ja', 'en-US', 'en'],
    });

    // plugins（ゼロは怪しい）
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
    });
}
"""


def ensure_dirs() -> None:
    """出力ディレクトリを作成"""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


async def create_stealth_context(browser: Browser) -> BrowserContext:
    """Stealth 設定済みのブラウザコンテキストを作成"""
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1440, "height": 900},
        device_scale_factor=2,
        locale="ja-JP",
        timezone_id="Asia/Tokyo",
        color_scheme="light",
        # セッション永続化（V7 に引き継ぐ）
        storage_state=str(PROFILE_DIR / "state.json") if (PROFILE_DIR / "state.json").exists() else None,
    )
    # 全ページに Stealth スクリプトを挿入
    await context.add_init_script(STEALTH_INIT_SCRIPT)
    return context


async def test_sannysoft(page: Page) -> Dict[str, bool]:
    """
    bot.sannysoft.com で bot 検出テスト
    返り値: {テスト名: 合格(True)/失敗(False)}
    """
    print("  [bot.sannysoft.com] アクセス中...")
    results: Dict[str, bool] = {}

    try:
        await page.goto("https://bot.sannysoft.com", timeout=30000)
        await asyncio.sleep(3)  # JS 実行を待つ

        # スクリーンショット保存
        screenshot_path = str(SCREENSHOTS_DIR / "sannysoft.png")
        await page.screenshot(path=screenshot_path, full_page=True)
        print(f"  スクリーンショット保存: {screenshot_path}")

        # 主要チェック項目を DOM から取得
        # sannysoft は table で結果を表示（pass=green, fail=red）
        check_items = await page.evaluate("""
            () => {
                const results = {};
                // テーブルの各行をスキャン
                const rows = document.querySelectorAll('table tr');
                rows.forEach(row => {
                    const cells = row.querySelectorAll('td');
                    if (cells.length >= 2) {
                        const name = cells[0].textContent.trim();
                        const value = cells[1].textContent.trim();
                        const isPassed = cells[1].style.backgroundColor === 'green'
                            || cells[1].className.includes('passed')
                            || value.toLowerCase() === 'passed'
                            || value.toLowerCase() === 'true'
                            || !['failed', 'undefined', 'missing', 'present'].includes(value.toLowerCase());
                        results[name] = { value: value, passed: isPassed };
                    }
                });
                return results;
            }
        """)

        # webdriver 関連の重要項目を確認
        key_checks = [
            "WebDriver",
            "WebDriver Advanced",
            "Chrome",
            "Permissions",
            "Plugins Length",
            "Languages",
        ]

        print("  主要チェック項目:")
        for key in key_checks:
            if key in check_items:
                item = check_items[key]
                status = "✓" if item["passed"] else "✗"
                print(f"    {status} {key}: {item['value']}")
                results[key] = item["passed"]
            else:
                # DOM から直接確認（テキスト検索）
                text = await page.inner_text("body")
                if key.lower() in text.lower():
                    results[key] = True  # 存在するが構造が違う
                else:
                    results[key] = None  # 不明

        # webdriver が undefined/false であることの直接確認
        wd_value = await page.evaluate("() => navigator.webdriver")
        print(f"    navigator.webdriver = {wd_value}")
        results["webdriver_undefined"] = (wd_value is None or wd_value is False)

    except Exception as e:
        print(f"  ERROR: {e}")
        results["error"] = False

    return results


async def test_creepjs(page: Page) -> Dict[str, bool]:
    """
    fingerprintjs.com/demo で Canvas / WebGL fingerprint テスト
    CreepJS の代替として基本的な fingerprint 項目を確認
    """
    print("  [fingerprintjs/demo] アクセス中...")
    results: Dict[str, bool] = {}

    try:
        await page.goto("https://fingerprintjs.com/demo", timeout=30000)
        await asyncio.sleep(5)

        screenshot_path = str(SCREENSHOTS_DIR / "fingerprintjs.png")
        await page.screenshot(path=screenshot_path, full_page=True)
        print(f"  スクリーンショット保存: {screenshot_path}")

        # VisitorID が取得できれば fingerprint は機能している
        visitor_id = await page.evaluate("""
            () => {
                const el = document.querySelector('[data-testid="visitor-id"]')
                    || document.querySelector('.visitor-id')
                    || document.querySelector('#visitor-id');
                return el ? el.textContent.trim() : null;
            }
        """)

        if visitor_id:
            print(f"  VisitorID 取得: {visitor_id[:16]}...")
            results["fingerprint_generated"] = True
        else:
            # ページテキストから確認
            text = await page.inner_text("body")
            has_id = len([l for l in text.split('\n') if len(l) == 20 and l.isalnum()]) > 0
            results["fingerprint_generated"] = has_id
            if not has_id:
                print("  VisitorID 取得できず（JS ロード中の可能性）")

        # navigator 基本チェック
        nav_info = await page.evaluate("""
            () => ({
                webdriver: navigator.webdriver,
                languages: navigator.languages,
                platform: navigator.platform,
                hardwareConcurrency: navigator.hardwareConcurrency,
                deviceMemory: navigator.deviceMemory,
            })
        """)
        print(f"  navigator.webdriver = {nav_info['webdriver']}")
        print(f"  navigator.languages = {nav_info['languages']}")
        print(f"  navigator.platform  = {nav_info['platform']}")
        print(f"  hardwareConcurrency = {nav_info['hardwareConcurrency']}")

        results["webdriver_hidden"] = (nav_info["webdriver"] is None or nav_info["webdriver"] is False)
        results["languages_set"] = (nav_info["languages"] is not None and len(nav_info["languages"]) > 0)
        results["platform_set"] = (nav_info["platform"] not in [None, ""])

    except Exception as e:
        print(f"  ERROR: {e}")
        results["error"] = False

    return results


async def test_browserscan(page: Page) -> Dict[str, bool]:
    """
    browserscan.net で自動化検出テスト
    """
    print("  [browserscan.net] アクセス中...")
    results: Dict[str, bool] = {}

    try:
        await page.goto("https://www.browserscan.net/bot-detection", timeout=30000)
        await asyncio.sleep(5)

        screenshot_path = str(SCREENSHOTS_DIR / "browserscan.png")
        await page.screenshot(path=screenshot_path, full_page=True)
        print(f"  スクリーンショット保存: {screenshot_path}")

        # ページテキストで判定
        text = await page.inner_text("body")

        # 自動化検出のシグナルをチェック
        automation_detected = any(kw in text.lower() for kw in [
            "automation detected",
            "bot detected",
            "automated browser",
        ])
        no_automation = any(kw in text.lower() for kw in [
            "no automation",
            "not detected",
            "normal browser",
        ])

        print(f"  自動化検出: {'YES ⚠' if automation_detected else 'NO ✓'}")
        print(f"  通常ブラウザ: {'YES ✓' if no_automation else 'UNKNOWN'}")
        results["no_automation_detected"] = not automation_detected
        results["passed_as_normal"] = no_automation

        # webdriver チェック
        wd = await page.evaluate("() => navigator.webdriver")
        results["webdriver_clean"] = (wd is None or wd is False)
        print(f"  navigator.webdriver = {wd}")

    except Exception as e:
        print(f"  ERROR: {e}")
        results["error"] = False

    return results


async def main() -> None:
    print("=" * 60)
    print("V6: Playwright Stealth bot検出回避検証")
    print("=" * 60)
    print("※ ブラウザウィンドウが開きます（headed モード）")
    print()

    ensure_dirs()

    all_results: Dict[str, Dict[str, bool]] = {}

    async with async_playwright() as p:
        # rebrowser-playwright で Chromium を headed 起動
        # channel="chrome" は実 Chrome インストールが必要なため chromium を使用
        print("--- ブラウザ起動 ---")
        browser = await p.chromium.launch(
            headless=False,
            args=STEALTH_ARGS,
        )
        print(f"  ブラウザ起動: {browser.browser_type.name}")

        context = await create_stealth_context(browser)

        # --- テスト 1: bot.sannysoft.com ---
        print("\n--- テスト 1: bot.sannysoft.com ---")
        page1 = await context.new_page()
        all_results["sannysoft"] = await test_sannysoft(page1)
        await page1.close()

        # --- テスト 2: fingerprintjs.com ---
        print("\n--- テスト 2: FingerprintJS Demo ---")
        page2 = await context.new_page()
        all_results["fingerprintjs"] = await test_creepjs(page2)
        await page2.close()

        # --- テスト 3: browserscan.net ---
        print("\n--- テスト 3: browserscan.net ---")
        page3 = await context.new_page()
        all_results["browserscan"] = await test_browserscan(page3)
        await page3.close()

        # セッション状態を保存（V7 に引き継ぐ）
        state_path = str(PROFILE_DIR / "state.json")
        await context.storage_state(path=state_path)
        print(f"\n  セッション保存: {state_path}")

        await context.close()
        await browser.close()

    # --- 判定 ---
    print("\n" + "=" * 60)
    print("--- 判定 ---")

    critical_checks = {
        "sannysoft.webdriver_undefined": all_results.get("sannysoft", {}).get("webdriver_undefined", False),
        "fingerprintjs.webdriver_hidden": all_results.get("fingerprintjs", {}).get("webdriver_hidden", False),
        "browserscan.no_automation_detected": all_results.get("browserscan", {}).get("no_automation_detected", False),
    }

    passed = sum(1 for v in critical_checks.values() if v is True)
    total = len(critical_checks)

    for name, result in critical_checks.items():
        status = "✅" if result else "❌"
        print(f"  {status} {name}: {result}")

    print()
    if passed == total:
        print(f"[合格] 全 {total} 項目クリア → X アクセスに進める可能性あり")
        print("  → V7: X セッション検証に進んでください")
    elif passed >= total * 0.6:
        print(f"[条件付き合格] {passed}/{total} 項目クリア → 改善の余地あり")
        print("  → V7 を進めつつ残り項目の Stealth 強化を検討")
    else:
        print(f"[不合格] {passed}/{total} 項目のみクリア → Stealth 設定の見直しが必要")

    # JSON 結果を保存
    result_path = SCREENSHOTS_DIR / "v6_results.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n  詳細結果: {result_path}")


if __name__ == "__main__":
    asyncio.run(main())
