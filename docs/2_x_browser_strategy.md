# Part 2: X ブラウザアクセス戦略 詳細設計

> **実施タイミング**: Phase 0 **後半**（2 週目）。コアパイプライン（LLM / Qdrant / ソースアダプタ）の検証が完了してから着手する。X 検証の結果に関わらず Phase 1 には進める設計としている（D11）。

---

## 1. 現状分析: X の bot 検出体制（2026年3月時点）

### 1.1 最重要事実

2026年2月、X のプロダクト責任者 Nikita Bier が以下を明言した。

> "If a human is not tapping on the screen, the account and all associated accounts will likely be suspended — even if you're just experimenting."
> （人間が画面をタップしていなければ、そのアカウントと関連アカウント全てを停止する）

> "Any form of scraping or search that is automated will get caught currently."
> （自動化されたスクレイピングや検索は現在すべて検出される）

さらに X は検索コードベースを全面書き換え中で、bot 検出の完全刷新を含むと発表している。

### 1.2 X の検出レイヤー（2026年版）

| レイヤー | 検出対象 | 難易度 |
|----------|---------|--------|
| **L1: デバイス Fingerprint** | navigator.webdriver / WebGL / Canvas / フォント / Hardware Concurrency | 中（stealth plugin で対処可能） |
| **L2: ブラウザ環境** | CDP（Chrome DevTools Protocol）接続検出 / SwiftShader / headless indicators | 高（rebrowser-playwright が必要） |
| **L3: トラフィックパターン** | TLS fingerprint / IP 属性（DC vs 住宅） / リクエストタイミング | 高（住宅 IP + タイミング制御が必要） |
| **L4: 行動分析** | マウス軌跡の精度 / クリック間隔の均一性 / スクロール速度パターン | 最高（最も突破困難） |
| **L5: コンテンツ分析** | 投稿パターン / エンゲージメントの相関性 / ネットワーク分析 | 最高（AI ベースの検出） |
| **L6: セッション整合性** | Cookie の一貫性 / localStorage / タイムゾーン・言語設定の矛盾 | 中 |

### 1.3 アクション別リスク評価

| アクション | リスク | 根拠 |
|-----------|--------|------|
| タイムライン閲覧（スクロール） | **中** | パッシブ操作。検出されにくいが頻度が不自然なら危険 |
| 検索実行 | **高** | Bier が「自動検索は検出される」と明言 |
| 投稿を読む（個別ページ遷移） | **低〜中** | 通常のブラウジング行動 |
| いいね / リツイート | **最高** | 自動エンゲージメントは即停止対象 |
| 投稿・リプライ | **高** | コンテンツ自動化は検出対象（ただし API 経由なら許可） |
| フォロー / アンフォロー | **最高** | 明確に禁止。即停止 |
| DM 送信 | **最高** | 自動化は禁止 |

---

## 2. 設計方針

### 2.1 根本的な判断: 読取と書込の分離

X の 2026 年 2 月のポリシー強化を踏まえ、**読取操作と書込操作を完全に分離する**。

```
┌─────────────────────────────────────────────────────┐
│                  X アクセス戦略                       │
│                                                     │
│  ┌──────────────────┐    ┌───────────────────────┐  │
│  │  読取レイヤー      │    │  書込レイヤー          │  │
│  │  (ブラウザ操作)    │    │  (将来的に検討)        │  │
│  │                  │    │                       │  │
│  │  ・タイムライン   │    │  ・投稿               │  │
│  │    閲覧          │    │  ・リプライ            │  │
│  │  ・投稿内容の     │    │  ・いいね             │  │
│  │    読み取り       │    │                       │  │
│  │  ・トレンド確認   │    │  方法:                │  │
│  │  ・プロフィール   │    │  ① Bot ラベル付き     │  │
│  │    確認          │    │    アカウント          │  │
│  │                  │    │  ② 手動操作           │  │
│  │  方法:           │    │  ③ 将来の判断         │  │
│  │  Stealth Browser │    │                       │  │
│  └──────────────────┘    └───────────────────────┘  │
│                                                     │
│  優先度: 読取 >>> 書込                               │
│  Phase 1 は読取のみ。書込は Phase 3 以降で判断       │
└─────────────────────────────────────────────────────┘
```

### 2.2 判断根拠

| 観点 | 読取（閲覧） | 書込（投稿・エンゲージメント） |
|------|-------------|---------------------------|
| 検出リスク | 中（パッシブ操作） | 高〜最高（Bier 発言で明確） |
| Agent の価値 | 情報収集が最優先機能 | Phase 1 では不要 |
| アカウント喪失時の影響 | 新規アカウントで復旧可能 | 関連アカウント全停止のリスク |
| X 規約 | グレー（自動閲覧の明確な禁止条項なし） | 自動エンゲージメントは明確に禁止 |

### 2.3 書込（投稿）をやる場合の選択肢

Phase 3 以降で書込を追加する場合、以下の選択肢がある。

| 方法 | リスク | 実現性 | 備考 |
|------|--------|--------|------|
| **Bot ラベル付きアカウント** | 低 | 高 | X の規約で許可されている。プロフィールに Bot と明記 |
| **ブラウザ経由での投稿** | 高 | 中 | Stealth が完璧でも行動分析で検出される可能性 |
| **X API（将来検討）** | 低 | 高 | 規約準拠。ただし今回の方針はブラウザのみ |
| **手動 + Agent 下書き** | なし | 高 | Agent が下書きを生成、人間が確認して投稿 |

---

## 3. Stealth Architecture（読取レイヤー）

### 3.1 多層 Stealth 構成

読取操作を可能な限り安全に行うための 6 層構成。

```yaml
# config/browser/stealth.yaml

stealth:
  # L1: Fingerprint 偽装
  fingerprint:
    webdriver: remove              # navigator.webdriver を undefined に
    webgl:
      vendor: "Google Inc. (Apple)" # 実際のGPUに合わせる
      renderer: "ANGLE (Apple, Apple M4 Pro, OpenGL 4.1)"
    canvas_noise: 0.02             # Canvas fingerprint にノイズ追加
    hardware_concurrency: 10       # M4 Pro の実際のコア数に合わせる
    device_memory: 16              # 実際に近い値
    platform: "MacIntel"
    languages: ["ja-JP", "ja", "en-US", "en"]
    timezone: "Asia/Tokyo"

  # L2: ブラウザ環境
  browser:
    mode: headed                   # headless は検出されやすい
    channel: chrome                # 実際の Chrome を使用
    use_rebrowser: true            # rebrowser-playwright でバイナリレベルパッチ
    disable_cdp_detection: true    # CDP 接続の痕跡を隠蔽
    user_data_dir: "/data/browser-profile/x-account"
    viewport:
      width: 1440
      height: 900
      device_scale_factor: 2       # Retina

  # L3: ネットワーク
  network:
    ip_type: residential           # 住宅 IP を使用（DC IP は即検出）
    proxy:
      enabled: false               # Phase 0 ではプロキシなしで検証
      # 将来的に住宅プロキシを検討
    tls_fingerprint: chrome_131    # 実際の Chrome の TLS fingerprint

  # L4: 行動パターン（HumanBehavior Skill で制御）
  behavior:
    ref: "config/skills/human_behavior.yaml"

  # L5: セッション管理
  session:
    cookie_persistence: true       # Cookie をボリュームで永続化
    local_storage_persistence: true
    login_method: manual_first     # 初回は手動ログイン → 以降セッション維持
    session_check_interval_min: 60 # 60 分ごとにセッション有効性確認
    reauth_strategy: pause_and_notify # セッション切れ時は停止して通知
```

### 3.2 ブラウザコンテナ設計

```yaml
# docker-compose.yml（browser サービス抜粋）

browser:
  build:
    context: ./browser
    dockerfile: Dockerfile
  environment:
    - DISPLAY=:99
  volumes:
    - ./data/browser-profile:/data/browser-profile   # セッション永続化
    - ./config/browser:/config/browser:ro             # Stealth設定（YAML）
  ports:
    - "5900:5900"    # VNC（デバッグ・監視用）
    - "9222:9222"    # CDP（agent-core からの接続用）
  deploy:
    resources:
      limits:
        cpus: "2"
        memory: 3G
  restart: unless-stopped
```

```dockerfile
# browser/Dockerfile

FROM mcr.microsoft.com/playwright:v1.52.0-noble

# VNC サーバー（headed モード表示用）
RUN apt-get update && apt-get install -y \
    x11vnc xvfb fluxbox \
    && rm -rf /var/lib/apt/lists/*

# rebrowser-playwright（バイナリレベルの stealth パッチ）
RUN npm install rebrowser-playwright

# 実際の Chrome をインストール（channel: chrome 用）
RUN wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && dpkg -i google-chrome-stable_current_amd64.deb || true \
    && apt-get -f install -y \
    && rm google-chrome-stable_current_amd64.deb

# CDP サーバー起動スクリプト
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5900 9222
CMD ["/entrypoint.sh"]
```

### 3.3 初回セッション確立フロー

X への初回ログインは手動で行い、以降はセッションを永続化する。

```
[Phase 0: 初回セットアップ]

1. VNC (localhost:5900) でブラウザコンテナに接続
2. 人間が手動で X にログイン
3. 2FA 認証を完了
4. ブラウザプロファイルが /data/browser-profile/ に保存される
   ├── Cookies
   ├── LocalStorage
   ├── SessionStorage
   └── IndexedDB
5. 以降の Agent 操作はこのプロファイルを引き継ぐ

[セッション切れ時]
1. Agent がセッション無効を検知
2. 全操作を一時停止
3. Dashboard / Discord に通知（JSON）
4. 人間が VNC 経由で手動再認証
5. Agent が操作を再開
```

---

## 4. HumanBehavior Skill 設計

### 4.1 概要

bot 検出の最大の戦場は「行動パターン分析」。
マウス移動の軌跡、クリックのタイミング、スクロール速度、ページ滞在時間を
人間的に揺らがせる Skill を設計する。

### 4.2 Skill 定義（YAML）

```yaml
# config/skills/human_behavior.yaml

name: human_behavior
category: browser
description: "ブラウザ操作に人間的な揺らぎを付与するメタSkill"

parameters:

  # --- マウス移動 ---
  mouse:
    move:
      algorithm: bezier_with_perturbation
      # 完璧なベジェ曲線ではなく、途中に微細な揺らぎを加える
      perturbation_px: [1, 5]       # 1〜5px のランダムな偏差
      speed:
        base_px_per_sec: [400, 1200]  # 人間のマウス速度範囲
        acceleration_curve: ease_in_out_with_noise
        # 始点でゆっくり → 加速 → 終点でゆっくり + ノイズ
      overshoot:
        probability: 0.08            # 8% の確率でターゲットを通り過ぎる
        correction_delay_ms: [50, 200] # 通り過ぎた後の修正までの遅延
    click:
      pre_click_hover_ms: [30, 150]  # クリック前のホバー時間
      click_duration_ms: [50, 120]   # マウスボタン押下時間
      double_click_interval_ms: [80, 200]
      miss_click:
        probability: 0.02            # 2% の確率でクリックミス
        recovery_action: click_correct_target

  # --- スクロール ---
  scroll:
    pattern: variable_with_pauses
    speed:
      base_px_per_scroll: [80, 300]  # 1回のスクロール量
      variation: 0.3                 # 30% のランダム変動
    direction:
      reverse_probability: 0.05      # 5% の確率で少し戻る（読み直し挙動）
    pause:
      probability: 0.15              # 15% の確率でスクロール中に一時停止
      duration_ms: [500, 3000]       # 停止時間（コンテンツを読んでいる風）
    content_aware:
      enabled: true
      # ページ内のテキスト量に応じて滞在時間を調整
      reading_speed_wpm: [150, 300]  # 日本語の読書速度幅
      image_dwell_ms: [800, 2000]    # 画像での停止時間

  # --- タイピング ---
  typing:
    wpm_range: [30, 60]              # 日本語入力速度（変換込み）
    inter_key_delay_ms:
      base: [50, 200]
      burst_probability: 0.1         # 10% で素早い連続入力（慣れた単語）
      pause_probability: 0.08        # 8% で思考停止（次の入力を考える）
      pause_duration_ms: [500, 2000]
    typo:
      probability: 0.015             # 1.5% でタイプミス
      correction_delay_ms: [300, 800] # ミスに気づくまでの時間
      correction_method: backspace_and_retype

  # --- ページ遷移 ---
  navigation:
    pre_click_delay_ms: [200, 1500]  # リンクをクリックする前の「考える」時間
    page_load_patience_sec: [3, 15]  # ページ読み込み完了を待つ時間のばらつき
    tab_behavior:
      new_tab_probability: 0.3       # 30% で新しいタブで開く
      tab_switch_delay_ms: [500, 2000]

  # --- 全体タイミング ---
  timing:
    action_interval:
      distribution: poisson
      lambda_sec: 5.0                # 平均5秒間隔でアクション
      min_sec: 1.0
      max_sec: 30.0
    session_duration:
      min_min: 5                     # 最短5分のセッション
      max_min: 45                    # 最長45分のセッション
      # 人間は45分以上連続でXを見続けることは少ない
    break_between_sessions:
      min_min: 10
      max_min: 120                   # セッション間は10分〜2時間の休憩
    daily_active_hours:
      # 日本時間で自然な活動時間帯
      active_ranges:
        - start: "07:00"
          end: "09:00"
          weight: 0.7               # 朝の確認（やや軽め）
        - start: "12:00"
          end: "13:00"
          weight: 0.5               # 昼休み
        - start: "18:00"
          end: "23:00"
          weight: 1.0               # 夜がメイン活動時間
        - start: "23:00"
          end: "01:00"
          weight: 0.3               # 深夜（まれに）
      inactive_ranges:
        - start: "02:00"
          end: "06:00"              # この時間帯は操作しない

  # --- アイドル行動 ---
  idle:
    enabled: true
    # セッション中の「何もしない」時間
    frequency: 0.1                   # 10% の時間はアイドル状態
    behaviors:
      - type: stare                  # ページを眺めているだけ
        duration_ms: [2000, 8000]
      - type: tab_switch_and_back    # 別タブに切り替えて戻る
        duration_ms: [3000, 15000]
      - type: scroll_up_down         # 少し上に戻って下に行く
        duration_ms: [1000, 5000]
```

### 4.3 行動パターンの数学的モデル

```
操作間隔: Poisson分布（λ = 5秒）
  → 実際の人間は「次の操作まで平均5秒」のような
     指数分布的な待ち時間を持つ

セッション長: 対数正規分布（μ = ln(20), σ = 0.5）
  → 中央値20分、大半が10〜40分に収まる

1日の操作回数: 正規分布（μ = 150, σ = 50）
  → 1日あたり100〜200操作が自然

時間帯ごとの活動量: 重み付きスケジュール
  → 朝・昼・夜の活動パターンを人間の生活リズムに合わせる
```

---

## 5. X 操作 Skill 設計

> **アダプタパターン適用（D3）**: X の読取操作は独立 Skill（browse_x_timeline 等）ではなく、`browse_source` Skill の **ソースアダプタ**（config/sources/x_timeline.yaml, config/sources/x_search.yaml）として実装する。以下の YAML 定義はアダプタ設定 + browse_source 内部での処理仕様として読むこと。

### 5.1 読取系アダプタ（Phase 1 対象）

#### x_timeline アダプタ

```yaml
# config/sources/x_timeline.yaml（ソースアダプタ定義）
# browse_source Skill が参照する。旧 browse_x_timeline Skill に相当

name: browse_x_timeline
category: perception
description: "Xのホームタイムラインをスクロールし、投稿を収集する"

input_schema:
  max_posts: int          # 収集する最大投稿数
  topic_filter: str       # 関心トピック（LLM でフィルタリング）
  scroll_depth: int       # スクロールする回数

output_schema:
  posts:
    - id: str
      author: str
      content: str
      timestamp: str
      engagement:
        likes: int
        retweets: int
        replies: int
      media_urls: list[str]
      is_relevant: bool     # topic_filter に対する関連性
  collected_at: str
  scroll_count: int
  session_duration_sec: int

execution:
  timeout_sec: 300
  max_retries: 1
  requires:
    - browser
    - stealth
    - human_behavior

  steps:
    - action: navigate
      url: "https://x.com/home"
      wait: page_load

    - action: verify_session
      on_failure: pause_and_notify

    - action: scroll_and_collect
      use_skill: human_behavior
      # スクロールのたびにDOMから投稿を抽出
      # human_behavior の scroll 設定に従って自然にスクロール

    - action: extract_posts
      method: dom_parse
      # Playwright の locator で投稿要素を取得
      selectors:
        post_container: "article[data-testid='tweet']"
        author: "[data-testid='User-Name']"
        content: "[data-testid='tweetText']"
        timestamp: "time"

    - action: filter_by_relevance
      use_model: qwen3-4b    # 軽量モデルで関連性判定
      prompt: |
        以下の投稿がトピック「{topic_filter}」に関連するか判定してください。
        関連する場合は true、関連しない場合は false を返してください。

  rate_limit:
    max_sessions_per_hour: 2
    max_scrolls_per_session: 30
    cool_down_min: 30
```

#### browse_x_search

```yaml
# config/skills/browse_x_search.yaml

name: browse_x_search
category: perception
description: "X の検索機能でキーワード検索し、結果を収集する"

# 注意: Nikita Bier が「自動検索は検出される」と明言
# → 使用頻度を極端に低く設定し、人間的パターンを厳格に適用

input_schema:
  query: str
  search_type: str        # "latest" | "top" | "people" | "media"
  max_results: int

output_schema:
  results:
    - id: str
      author: str
      content: str
      timestamp: str
      engagement: dict
  query_used: str
  search_type: str
  collected_at: str

execution:
  timeout_sec: 180
  max_retries: 0           # 検索は失敗してもリトライしない（リスク回避）
  requires:
    - browser
    - stealth
    - human_behavior

  rate_limit:
    max_searches_per_day: 5   # 1日5回まで（非常に控えめ）
    min_interval_between_searches_min: 60  # 検索間は最低60分空ける
    # 人間でも1時間に何度も検索しない

  risk_level: high
  fallback_on_detection:
    action: immediate_pause
    cool_down_hours: 6       # 検出された場合は6時間停止
    notify: true
```

#### browse_x_profile

```yaml
# config/skills/browse_x_profile.yaml

name: browse_x_profile
category: perception
description: "特定ユーザーのプロフィールページを閲覧し、最近の投稿を収集する"

input_schema:
  username: str
  max_posts: int

output_schema:
  profile:
    display_name: str
    bio: str
    followers: int
    following: int
  posts: list[dict]
  collected_at: str

execution:
  timeout_sec: 120
  max_retries: 1
  requires:
    - browser
    - stealth
    - human_behavior

  rate_limit:
    max_profiles_per_hour: 3
    min_interval_between_visits_min: 15

  risk_level: medium
```

### 5.2 操作メタ Skill

#### verify_x_session

```yaml
# config/skills/verify_x_session.yaml

name: verify_x_session
category: browser
description: "Xのセッションが有効かを確認し、無効なら停止・通知する"

input_schema: {}

output_schema:
  session_valid: bool
  detected_issues:
    - type: str           # "captcha" | "login_required" | "suspended" | "rate_limited"
      details: str

execution:
  timeout_sec: 30
  max_retries: 0

  checks:
    - name: login_check
      method: check_element_exists
      selector: "[data-testid='SideNav_AccountSwitcher_Button']"
      # ログイン済みの場合にのみ表示される要素

    - name: captcha_check
      method: check_url_contains
      pattern: "challenge"
      # CAPTCHA ページにリダイレクトされていないか

    - name: suspension_check
      method: check_element_exists
      selector: "[data-testid='emptyState']"
      # アカウント停止ページの要素

  on_failure:
    captcha: pause_and_notify
    login_required: pause_and_notify
    suspended: emergency_stop      # 全操作を即時停止
    rate_limited: cool_down_2h
```

### 5.3 検出回避の判断フロー

```
[X操作を実行する前]
     │
     ▼
[現在の時間帯は active_ranges 内か？]
     │
     ├── No → 操作しない（人間は寝ている時間）
     │
     └── Yes ↓
         │
         ▼
    [今日のセッション回数 < 上限か？]
         │
         ├── No → 操作しない（今日はもう十分アクセスした）
         │
         └── Yes ↓
             │
             ▼
        [前回セッションからの経過時間 > break_between_sessions.min か？]
             │
             ├── No → 待機（連続アクセスは不自然）
             │
             └── Yes ↓
                 │
                 ▼
            [verify_x_session を実行]
                 │
                 ├── session_valid: false → 停止 + 通知
                 │
                 └── session_valid: true ↓
                     │
                     ▼
                [human_behavior のタイミング設定に従って操作開始]
                     │
                     ▼
                [session_duration が上限に達したら自然に終了]
                     │
                     ▼
                [次のセッションまで break]
```

---

## 6. セキュリティとリスク管理

### 6.1 アカウント保護戦略

```yaml
# config/safety_x.yaml

account_protection:
  # メインアカウントは使わない
  use_dedicated_account: true
  account_type: bot_labeled          # プロフィールに Bot と明記

  # アカウントの「温め」（新規アカウントはいきなり自動化しない）
  warming:
    phase_1_days: 14                 # 最初の2週間は手動操作のみ
    phase_2_days: 14                 # 次の2週間は1日1-2回の自動閲覧
    phase_3: full_auto               # 1ヶ月後から通常運用

  # 検出時の段階的対応
  detection_response:
    captcha_triggered:
      action: immediate_pause
      cool_down_hours: 6
      reduce_frequency: 0.5          # 頻度を50%に低減
      notify: true

    rate_limited:
      action: pause
      cool_down_hours: 2
      notify: true

    account_locked:
      action: emergency_stop
      notify: true
      # 人間が手動で解決するまで一切の操作を停止

    account_suspended:
      action: emergency_stop
      notify: true
      # 全関連操作を停止
      # 別アカウントへの自動切り替えはしない（連鎖停止のリスク）

  # 操作の上限（1日あたり）
  daily_limits:
    max_sessions: 6
    max_total_scrolls: 100
    max_searches: 5
    max_profile_visits: 10
    max_pages_viewed: 50
```

### 6.2 監視ダッシュボード表示項目

```json
{
  "x_status": {
    "session_valid": true,
    "last_access": "2026-03-31T19:30:00+09:00",
    "today_sessions": 3,
    "today_scrolls": 45,
    "today_searches": 2,
    "detection_events": 0,
    "current_frequency_modifier": 1.0,
    "account_health": "green"
  }
}
```

---

## 7. 代替情報源（X がブロックされた場合のフォールバック）

X へのブラウザアクセスが恒久的に困難になった場合の代替戦略。
Agent の情報収集能力を X だけに依存させない。

| 代替ソース | 取得方法 | 情報の質 | 実装難易度 |
|-----------|---------|---------|-----------|
| **RSS フィード** | 直接取得（ブラウザ不要） | 中（X の生データとは異なる） | 低 |
| **ニュースサイト直接巡回** | Playwright（Stealth 不要） | 高（一次ソース） | 低 |
| **GitHub Trending** | Playwright / API | 高（技術情報） | 低 |
| **Hacker News** | API（公式） | 高（技術コミュニティ） | 低 |
| **Reddit** | Playwright / API | 中〜高 | 中 |
| **Nitter 系ミラー** | 直接取得 | 中（サービス安定性に依存） | 低 |

```yaml
# config/fallback_sources.yaml

fallback:
  trigger: x_access_blocked_24h     # Xに24時間アクセスできない場合に発動

  sources:
    - name: hacker_news
      type: api
      url: "https://hacker-news.firebaseio.com/v0/"
      frequency_min: 60
      priority: 1

    - name: github_trending
      type: browser
      url: "https://github.com/trending"
      frequency_min: 360
      priority: 2
      stealth_required: false        # GitHub には Stealth 不要

    - name: techcrunch
      type: browser
      url: "https://techcrunch.com"
      frequency_min: 120
      priority: 3
      stealth_required: false

    - name: rss_feeds
      type: rss
      feeds:
        - "https://feeds.feedburner.com/TechCrunch"
        - "https://www.theverge.com/rss/index.xml"
      frequency_min: 60
      priority: 1
```

---

## 8. Phase 0 検証項目

> **注意**: X 検証は Phase 0 **後半**（2 週目）に実施する。Phase 0 前半ではコアパイプライン（Qwen3.5 推論速度、Qdrant、ソースアダプタ）の検証を優先する。コアパイプラインが動作することを先に確認し、X 検証の結果に関わらず Phase 1 に進める状態を作る（D11）。

X アクセス戦略に関する Phase 0 での検証項目。

### 8.1 検証チェックリスト

| # | 検証項目 | 合格基準 | 方法 |
|---|---------|---------|------|
| 1 | bot.sannysoft.com 全テスト通過 | 全項目 green | Docker 内ブラウザで sannysoft にアクセス |
| 2 | browserscan.net CDP 検出回避 | "No automation detected" | rebrowser-playwright 使用 |
| 3 | X ログイン維持（手動ログイン後） | 24 時間後もセッション有効 | 手動ログイン → 24h 後に verify_x_session |
| 4 | X タイムライン閲覧（10 回試行） | 8/10 回成功 | browse_x_timeline を human_behavior 付きで実行 |
| 5 | X 検索（5 回試行） | 3/5 回成功 | browse_x_search を低頻度で実行 |
| 6 | 72 時間連続運用テスト | アカウント停止なし | 低頻度（1 日 3 セッション）で 3 日間稼働 |

### 8.2 Go / No-Go 判定

| 結果 | 判定 | 次のアクション |
|------|------|--------------|
| 6/6 通過 | **Go** | Phase 1 に進む |
| 4-5/6 通過 | **条件付き Go** | 不合格項目を改善してから Phase 1 |
| 1-3 通過（X アクセス不安定） | **方針転換** | X は代替ソースに切り替え、他サイトの閲覧に注力 |
| 検証中にアカウント停止 | **戦略再検討** | ブラウザ操作の X アクセスを断念し、Bot ラベル + API 方式を検討 |

---

## 9. 未決定事項

| 項目 | 選択肢 | 判断時期 |
|------|--------|---------|
| 住宅プロキシの使用 | 使う / 使わない（自宅 IP で十分か） | Phase 0 検証後 |
| X 投稿機能の実装 | ブラウザ / Bot ラベル + API / 手動 / やらない | Phase 3 |
| Python stealth vs Node.js rebrowser | Python のみ / Node.js subprocess / ハイブリッド | Phase 0 検証後 |
| X 専用アカウントの作成 | 新規作成 / 既存活用 | Phase 0 開始前 |
| CAPTCHA 解決サービスの利用 | 使う / 使わない（手動対応のみ） | Phase 1 以降 |



---
