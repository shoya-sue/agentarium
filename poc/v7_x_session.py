"""
V7: X（Twitter）セッション維持・タイムライン閲覧検証
合格基準:
  - 手動ログイン後のセッションが維持されること
  - タイムライン閲覧 10 回中 8 回以上成功
  - 検索 5 回中 3 回以上成功
  - 72 時間連続運用でアカウント停止なし

実行フロー:
  1. --setup モード（CDP）: 実際の Chrome を起動して手動 X ログイン。
                            ログイン後 CDP 経由で Cookie を取得し state.json に保存。
                            → X のフォーム入力 bot 検出を回避
  2. --test  モード: 保存済みセッションを rebrowser-playwright で読み込み、
                     タイムライン閲覧・検索を実行
  3. --check モード: セッションが有効かどうかを確認するだけ

使用例:
  python3 poc/v7_x_session.py --setup --character zephyr
  python3 poc/v7_x_session.py --setup --character lynx
  python3 poc/v7_x_session.py --test  --character zephyr
  python3 poc/v7_x_session.py --check --character zephyr

注意:
  - Phase 0 は読取（閲覧）のみ。いいね・RT・フォロー等は禁止
  - セッション状態は data/browser-profile/{character}/state.json に保存
  - --setup は実際の Chrome を使用（rebrowser-playwright 不使用）
  - --test / --check は rebrowser-playwright を使用（Stealth 閲覧）
"""

import argparse
import asyncio
import json
import random
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

from rebrowser_playwright.async_api import async_playwright, Browser, BrowserContext, Page

# プロジェクトルート
PROJECT_ROOT = Path(__file__).parent.parent

# キャラクター名（config/characters/ と対応）
CHARACTERS = ["zephyr", "lynx"]

# X のエンドポイント
X_HOME_URL = "https://x.com/home"
X_LOGIN_URL = "https://x.com/login"

# CDP デバッグポート（--setup 専用）
CDP_PORT = 9222
CDP_URL = f"http://localhost:{CDP_PORT}"

# macOS の Chrome パス候補（上から順に探す）
CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
]

# Stealth 設定（--test / --check で使用）
STEALTH_ARGS = [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--lang=ja-JP",
    "--force-device-scale-factor=2",
]

STEALTH_INIT_SCRIPT = """
() => {
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
        configurable: true,
    });
    if (!window.chrome) {
        window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
    }
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
    );
    Object.defineProperty(navigator, 'languages', { get: () => ['ja-JP', 'ja', 'en-US', 'en'] });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
}
"""


# ---------------------------------------------------------------------------
# パスユーティリティ
# ---------------------------------------------------------------------------

def get_profile_dir(character: str) -> Path:
    """キャラクター別のセッション保存ディレクトリを返す"""
    return PROJECT_ROOT / "data" / "browser-profile" / character


def get_screenshots_dir(character: str) -> Path:
    return PROJECT_ROOT / "data" / "outputs" / f"v7_{character}_screenshots"


def ensure_dirs(character: str) -> None:
    get_profile_dir(character).mkdir(parents=True, exist_ok=True)
    get_screenshots_dir(character).mkdir(parents=True, exist_ok=True)


def find_chrome() -> Optional[str]:
    """インストール済みの Chrome / Chromium パスを返す。見つからなければ None"""
    for path in CHROME_PATHS:
        if Path(path).exists():
            return path
    return None


# ---------------------------------------------------------------------------
# --setup モード（CDP アプローチ）
# ---------------------------------------------------------------------------

async def setup_mode_cdp(character: str) -> None:
    """
    実際の Chrome を CDP モードで起動してユーザーに手動ログインしてもらい、
    Playwright CDP 接続で storage_state を取得して state.json に保存する。

    ポイント:
      - rebrowser-playwright は使わない（ログイン画面での bot 検出を回避）
      - 取得した state.json は --test / --check で rebrowser-playwright が読み込む
    """
    profile_dir = get_profile_dir(character)
    state_path = profile_dir / "state.json"
    # Chrome の一時プロファイル（毎回クリーンな状態でログイン）
    tmp_profile = f"/tmp/chrome-x-setup-{character}"

    chrome_path = find_chrome()
    if not chrome_path:
        print("ERROR: Chrome / Chromium が見つかりません。")
        print("  インストール先候補:")
        for p in CHROME_PATHS:
            print(f"    {p}")
        return

    print(f"\n--- セットアップモード（CDP）: {character} ---")
    print(f"  Chrome: {chrome_path}")
    print(f"  一時プロファイル: {tmp_profile}")
    print()

    # 実際の Chrome を CDP モードで起動（Playwright 制御なし）
    proc = subprocess.Popen(
        [
            chrome_path,
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={tmp_profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "https://x.com/login",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    print("  Chrome が起動しました。")
    print(f"  [{character}] の X アカウントにログインしてください。")
    print("  2FA がある場合もここで完了させてください。")
    print()
    print("  ログイン完了後、このターミナルで Enter を押してください...")

    # ユーザーの操作を待つ
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, input)

    # CDP 経由で Playwright を接続し Cookie を取得
    print("  CDP 接続中...")
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"  ERROR: CDP 接続失敗: {e}")
            print(f"  Chrome が {CDP_URL} でリッスンしているか確認してください。")
            proc.terminate()
            return

        contexts = browser.contexts
        if not contexts:
            print("  ERROR: ブラウザコンテキストが見つかりません。")
            await browser.close()
            proc.terminate()
            return

        context = contexts[0]

        # ログイン状態を確認
        pages = context.pages
        page = pages[0] if pages else await context.new_page()

        current_url = page.url
        print(f"  現在 URL: {current_url}")

        if "login" in current_url or "flow" in current_url:
            print("  ⚠ ログインページが表示されています。ログインを完了してから再実行してください。")
            await browser.close()
            proc.terminate()
            return

        # storage_state（Cookie + localStorage）を保存
        await context.storage_state(path=str(state_path))
        print(f"  ✅ セッション保存: {state_path}")
        print(f"     → 次回は --test --character {character} で自動テストを実行できます。")

        await browser.close()

    # Chrome プロセスを終了
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

    print("  Chrome を終了しました。")


# ---------------------------------------------------------------------------
# Stealth コンテキスト（--test / --check 共通）
# ---------------------------------------------------------------------------

async def create_stealth_context(browser: Browser, character: str) -> BrowserContext:
    """rebrowser-playwright の Stealth コンテキスト。保存済みセッションを読み込む"""
    state_path = get_profile_dir(character) / "state.json"
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
        storage_state=str(state_path) if state_path.exists() else None,
    )
    await context.add_init_script(STEALTH_INIT_SCRIPT)
    return context


async def save_session(context: BrowserContext, character: str) -> None:
    """セッション状態を更新保存"""
    state_path = str(get_profile_dir(character) / "state.json")
    await context.storage_state(path=state_path)
    print(f"  セッション更新: {state_path}")


# ---------------------------------------------------------------------------
# ログイン確認
# ---------------------------------------------------------------------------

async def check_logged_in(page: Page) -> bool:
    """X にログイン済みかどうかを確認"""
    try:
        await page.goto(X_HOME_URL, timeout=30000)
        await asyncio.sleep(3)
        current_url = page.url
        if "login" in current_url or "flow" in current_url:
            return False
        timeline = await page.query_selector('[data-testid="primaryColumn"]')
        return timeline is not None
    except Exception as e:
        print(f"  ログイン確認エラー: {e}")
        return False


# ---------------------------------------------------------------------------
# タイムライン閲覧・検索（--test で使用）
# ---------------------------------------------------------------------------

def human_delay(min_ms: int = 1000, max_ms: int = 3000) -> float:
    """人間らしいランダム待機時間（秒）"""
    return random.uniform(min_ms, max_ms) / 1000.0


async def browse_timeline(page: Page, trial: int, screenshots_dir: Path) -> bool:
    """タイムライン閲覧テスト（1回）"""
    try:
        await page.goto(X_HOME_URL, timeout=30000)
        await asyncio.sleep(human_delay(2000, 4000))

        timeline = await page.query_selector('[data-testid="primaryColumn"]')
        if not timeline:
            print(f"  [{trial}] FAIL: タイムライン要素なし（ログイン切れ？）")
            return False

        tweets = await page.query_selector_all('[data-testid="tweet"]')
        if len(tweets) == 0:
            articles = await page.query_selector_all("article")
            if len(articles) == 0:
                print(f"  [{trial}] FAIL: ツイートが表示されない")
                return False
            tweet_count = len(articles)
        else:
            tweet_count = len(tweets)

        await page.mouse.wheel(0, random.randint(300, 800))
        await asyncio.sleep(human_delay(1000, 2000))

        if trial == 1:
            path = str(screenshots_dir / "timeline_trial01.png")
            await page.screenshot(path=path)
            print(f"  スクリーンショット: {path}")

        print(f"  [{trial}] OK: {tweet_count} tweets 表示")
        return True

    except Exception as e:
        print(f"  [{trial}] ERROR: {e}")
        return False


async def search_x(page: Page, query: str, trial: int) -> bool:
    """X 検索テスト（1回）"""
    try:
        search_url = f"https://x.com/search?q={query}&src=typed_query&f=live"
        await page.goto(search_url, timeout=30000)
        await asyncio.sleep(human_delay(2000, 4000))

        current_url = page.url
        if "login" in current_url or "flow" in current_url:
            print(f"  [{trial}] FAIL: 検索でログインページにリダイレクト（セッション切れ）")
            return False

        tweets = await page.query_selector_all('[data-testid="tweet"]')
        articles = await page.query_selector_all("article")
        count = max(len(tweets), len(articles))

        no_results = await page.query_selector('[data-testid="empty_state_header"]')
        if no_results:
            print(f"  [{trial}] OK（検索結果なし）: '{query}'")
            return True

        if count > 0:
            print(f"  [{trial}] OK: '{query}' → {count} 件")
        else:
            print(f"  [{trial}] FAIL: 検索結果取得できず")
            return False

        await page.mouse.wheel(0, random.randint(200, 500))
        await asyncio.sleep(human_delay(500, 1500))
        return True

    except Exception as e:
        print(f"  [{trial}] ERROR: {e}")
        return False


# ---------------------------------------------------------------------------
# --test モード
# ---------------------------------------------------------------------------

async def test_mode(character: str) -> None:
    """保存済みセッションで自動閲覧テストを実行"""
    state_path = get_profile_dir(character) / "state.json"
    screenshots_dir = get_screenshots_dir(character)

    if not state_path.exists():
        print(f"ERROR: セッションファイルが存在しません: {state_path}")
        print(f"  先に --setup --character {character} を実行してください。")
        return

    print(f"\n--- テストモード: {character} ---")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=STEALTH_ARGS)
        context = await create_stealth_context(browser, character)
        page = await context.new_page()

        # ログイン確認
        print("  ログイン状態確認...")
        logged_in = await check_logged_in(page)
        if not logged_in:
            print(f"  ❌ セッション切れ。--setup --character {character} で再ログインしてください。")
            await context.close()
            await browser.close()
            return
        print("  ✅ ログイン確認: 成功")

        # タイムライン閲覧テスト（10回）
        print("\n--- タイムライン閲覧テスト（10回）---")
        timeline_results: List[bool] = []
        for i in range(1, 11):
            result = await browse_timeline(page, i, screenshots_dir)
            timeline_results.append(result)
            if i < 10:
                await asyncio.sleep(human_delay(3000, 8000))

        timeline_ok = sum(timeline_results)
        print(f"\n  [{'OK' if timeline_ok >= 8 else 'FAIL'}] タイムライン: {timeline_ok}/10 成功 (基準: 8/10 以上)")

        # 検索テスト（5回）
        print("\n--- 検索テスト（5回）---")
        search_queries = ["AI agent", "LLM 2026", "Qwen3.5", "機械学習", "Python"]
        search_results: List[bool] = []
        for i, query in enumerate(search_queries, 1):
            result = await search_x(page, query, i)
            search_results.append(result)
            if i < len(search_queries):
                await asyncio.sleep(human_delay(5000, 12000))

        search_ok = sum(search_results)
        print(f"\n  [{'OK' if search_ok >= 3 else 'FAIL'}] 検索: {search_ok}/5 成功 (基準: 3/5 以上)")

        # セッション更新保存
        await save_session(context, character)
        await context.close()
        await browser.close()

    # 最終判定
    print("\n" + "=" * 60)
    print(f"--- V7 判定: {character} ---")
    timeline_passed = timeline_ok >= 8
    search_passed = search_ok >= 3

    print(f"  タイムライン: {'✅' if timeline_passed else '❌'} {timeline_ok}/10")
    print(f"  検索:         {'✅' if search_passed else '❌'} {search_ok}/5")

    if timeline_passed and search_passed:
        print("\n[合格] X アクセス Go → Phase 1 の patrol.yaml で x_timeline を enabled: true に")
    elif timeline_passed and not search_passed:
        print("\n[条件付き合格] タイムライン OK / 検索 NG")
        print("  → X は低頻度閲覧のみ可。検索はリスク高のため Phase 1 では無効化を推奨")
    elif not timeline_passed and search_passed:
        print("\n[条件付き不合格] タイムライン NG / 検索 OK")
        print("  → セッション安定性に問題あり。--setup で再取得を推奨")
    else:
        print("\n[不合格] 両方 NG → --setup で再取得、または X を代替ソースに置き換え")

    # 結果 JSON 保存
    result = {
        "character": character,
        "timeline": {"success": timeline_ok, "total": 10, "passed": timeline_passed, "details": timeline_results},
        "search": {"success": search_ok, "total": 5, "passed": search_passed, "details": search_results},
    }
    result_path = screenshots_dir / "v7_results.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n  詳細結果: {result_path}")


# ---------------------------------------------------------------------------
# --check モード
# ---------------------------------------------------------------------------

async def check_mode(character: str) -> None:
    """セッション確認のみ（短時間）"""
    state_path = get_profile_dir(character) / "state.json"
    screenshots_dir = get_screenshots_dir(character)

    if not state_path.exists():
        print(f"セッションファイルなし: {state_path}")
        print(f"  --setup --character {character} を実行してください。")
        return

    print(f"--- セッション確認: {character} ---")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=STEALTH_ARGS)
        context = await create_stealth_context(browser, character)
        page = await context.new_page()

        logged_in = await check_logged_in(page)
        current_url = page.url

        print(f"  セッション状態: {'✅ ログイン済み' if logged_in else '❌ 未ログイン / 切れ'}")
        print(f"  現在 URL: {current_url}")

        if logged_in:
            screenshot_path = str(screenshots_dir / "session_check.png")
            await page.screenshot(path=screenshot_path)
            print(f"  スクリーンショット: {screenshot_path}")

        await context.close()
        await browser.close()


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser(
        description="V7: X セッション検証",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python3 poc/v7_x_session.py --setup --character zephyr   # Zephyr 用セッション取得
  python3 poc/v7_x_session.py --setup --character lynx     # Lynx 用セッション取得
  python3 poc/v7_x_session.py --test  --character zephyr   # 自動テスト
  python3 poc/v7_x_session.py --check --character zephyr   # セッション確認
        """,
    )
    parser.add_argument("--setup", action="store_true", help="CDP で実 Chrome を起動してセッションを取得")
    parser.add_argument("--test",  action="store_true", help="保存済みセッションで自動テスト実行")
    parser.add_argument("--check", action="store_true", help="セッション状態の確認のみ")
    parser.add_argument(
        "--character",
        choices=CHARACTERS,
        required=True,
        help=f"キャラクター名 ({' / '.join(CHARACTERS)})",
    )
    args = parser.parse_args()

    if not (args.setup or args.test or args.check):
        parser.print_help()
        return

    print("=" * 60)
    print(f"V7: X セッション維持・閲覧検証  [{args.character}]")
    print("=" * 60)

    ensure_dirs(args.character)

    if args.setup:
        await setup_mode_cdp(args.character)
    elif args.test:
        await test_mode(args.character)
    elif args.check:
        await check_mode(args.character)


if __name__ == "__main__":
    asyncio.run(main())
