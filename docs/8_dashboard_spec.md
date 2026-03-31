# Agentarium Monitor — ダッシュボード仕様書

## 1. 概要

### 1.1 目的

AI Agent のリアルタイム動作状況を、非エンジニアにもわかりやすく可視化する Web ダッシュボード。

- **現在どの Skill が動いているか**がひと目でわかる
- **LLM への入力（プロンプト）と出力（レスポンス）** を確認できる
- **どの情報源から何件取得したか**を把握できる
- **エラーや詰まりがどこで発生しているか**を視覚的に特定できる

### 1.2 スコープ（READ-ONLY）

| 対象 | 説明 |
|------|------|
| ✅ 読み取り | SkillTrace JSON / Qdrant 統計 / スケジューラ状態 |
| ✅ 可視化 | タイムライン・グラフ・LLM I/O ビューア |
| ❌ 操作 | Agent への指示・Skill の起動・設定変更 |

エージェント本体（agent-core）のコードへの変更は**一切行わない**。

---

## 2. アーキテクチャ

### 2.1 全体構成

```
┌──────────────────────────────────────────────────────┐
│                    Docker Network                     │
│                                                      │
│  ┌─────────────┐     SkillTrace     ┌─────────────┐  │
│  │ agent-core  │ ──── JSON files ──►│  dashboard  │  │
│  │  (読取元)    │                    │  (SSE server│  │
│  └─────────────┘                    │  + Static)  │  │
│                                     └──────┬──────┘  │
│  ┌─────────────┐     REST API              │         │
│  │   qdrant    │ ─────────────────────────►│         │
│  │  (stats)    │                           │         │
│  └─────────────┘                      SSE stream     │
└──────────────────────────────────────────┼───────────┘
                                           │
                                    ┌──────▼──────┐
                                    │  Browser    │
                                    │ (GUI / HTML)│
                                    └─────────────┘
```

### 2.2 データフロー

```
agent-core
  └── SkillTrace.save()
        └── data/traces/{date}/{skill}/{trace_id}.json

dashboard server（Python FastAPI）
  ├── ファイル監視（watchfiles）
  │     data/traces/ の新規ファイルを検知
  │
  ├── SSE エンドポイント
  │     GET /api/events  → text/event-stream
  │
  ├── REST エンドポイント
  │     GET /api/traces?limit=50    最新トレース一覧
  │     GET /api/traces/{trace_id}  トレース詳細
  │     GET /api/scheduler/states   スケジューラ状態
  │     GET /api/qdrant/stats       Qdrant コレクション統計
  │
  └── Static ファイル配信
        GET /  → index.html（単一ページアプリ）
```

### 2.3 更新方式

| 方式 | 用途 | 更新頻度 |
|------|------|---------|
| SSE push | 新規 SkillTrace 検知時 | リアルタイム（~1秒以内） |
| REST ポーリング | Qdrant 統計 / スケジューラ状態 | 30秒ごと |

---

## 3. Docker Compose 設計

```yaml
# docker-compose.yml への追加分
dashboard:
  build:
    context: ./dashboard
    dockerfile: Dockerfile
  container_name: agentarium-dashboard
  ports:
    - "8080:8080"
  volumes:
    - ./data:/app/data:ro          # traces を読み取り専用でマウント
    - ./config:/app/config:ro      # スケジュール設定を読み取り
  environment:
    - QDRANT_URL=http://qdrant:6333
    - DATA_DIR=/app/data
    - PORT=8080
  depends_on:
    - qdrant
```

### ディレクトリ構成

```
dashboard/
├── Dockerfile
├── pyproject.toml       # FastAPI + watchfiles + httpx
├── src/
│   ├── main.py          # FastAPI アプリ本体
│   ├── watcher.py       # data/traces/ 監視 + SSE ブロードキャスト
│   ├── qdrant_stats.py  # Qdrant REST API からコレクション統計取得
│   └── scheduler_reader.py  # patrol.yaml + state ファイル読み取り
├── static/
│   ├── index.html       # SPA 本体
│   ├── style.css
│   └── app.js
└── poc/
    └── monitor.html     # POC（1ファイル完結）
```

---

## 4. UI レイアウト

### 4.1 全体レイアウト（デスクトップ）

```
┌────────────────────────────────────────────────────────────────┐
│  🤖 Agentarium Monitor    ● LIVE    Skills: 42  Errors: 1      │ ← ヘッダー
├──────────────┬─────────────────────────────┬───────────────────┤
│              │                             │                   │
│  スケジューラ  │    Skill タイムライン         │   LLM I/O         │
│  状態         │                             │   ビューア         │
│  （左パネル）  │   （中央メインパネル）         │   （右パネル）     │
│              │                             │                   │
│  [250px]     │   [flex-grow: 1]            │   [380px]         │
│              │                             │                   │
├──────────────┴─────────────────────────────┴───────────────────┤
│  エラー / 警告ログ（フッターバー）                                  │
└────────────────────────────────────────────────────────────────┘
```

### 4.2 左パネル — スケジューラ状態

```
┌─────────────────────┐
│ 📅 巡回スケジューラ   │
├─────────────────────┤
│ hacker_news         │
│  ✅ 最終: 14:23     │
│  ⏱ 次回: 15:23 (45分)│
│  ████░░░░ 62%       │ ← プログレスバー
├─────────────────────┤
│ rss_feeds           │
│  ✅ 最終: 14:58     │
│  ⏱ 次回: 15:58 (12分)│
│  █████████░ 90%     │
├─────────────────────┤
│ github_trending     │
│  ✅ 最終: 12:00     │
│  ⏱ 次回: 18:00 (3h) │
│  ██░░░░░░░ 22%      │
├─────────────────────┤
│ 🧠 Qdrant           │
├─────────────────────┤
│ episodic   1,234件  │
│ semantic     567件  │
│ procedural     0件  │
└─────────────────────┘
```

### 4.3 中央パネル — Skill タイムライン

```
┌─────────────────────────────────────────┐
│ Skill タイムライン         [直近 50件 ▼] │
├─────────────────────────────────────────┤
│                                         │
│ 15:03:42  browse_source                 │
│ ┌─────────────────────────────────┐     │
│ │ 🌐 hacker_news  ████████  245ms │ ✅  │
│ └─────────────────────────────────┘     │
│                                         │
│ 15:03:43  llm_call                      │
│ ┌─────────────────────────────────┐     │
│ │ 🤖 filter_relevance  ████  1.2s │ ✅  │  ← クリックで右パネルに I/O 展開
│ └─────────────────────────────────┘     │
│                                         │
│ 15:03:45  store_semantic                │
│ ┌─────────────────────────────────┐     │
│ │ 💾 +8件保存  ██  89ms           │ ✅  │
│ └─────────────────────────────────┘     │
│                                         │
│ 15:03:46  ⏳ llm_call（実行中...）       │
│ ┌─────────────────────────────────┐     │
│ │ 🤖 extract_knowledge  ░░░░░░░   │ 🔄  │  ← アニメーション
│ └─────────────────────────────────┘     │
│                                         │
│ ─────────────────── 15:02 ───────────── │
│                                         │
│ 15:02:11  fetch_rss                     │
│ ┌─────────────────────────────────┐     │
│ │ 📡 rss_feeds  ███  156ms        │ ✅  │
│ └─────────────────────────────────┘     │
│                                         │
│ 15:01:44  browse_source                 │
│ ┌─────────────────────────────────┐     │
│ │ 🌐 newspicks  timeout           │ ❌  │
│ └─────────────────────────────────┘     │
│                                         │
└─────────────────────────────────────────┘
```

### 4.4 右パネル — LLM I/O ビューア

```
┌───────────────────────────────────────┐
│ 🤖 LLM I/O ビューア                   │
│ llm_call @ 15:03:43                   │
├───────────────────────────────────────┤
│ モデル: qwen3.5-35b-a3b               │
│ トークン: prompt 412 / completion 89  │
│ 速度: 38.2 tok/s   所要: 1.2s         │
├───────────────────────────────────────┤
│ INPUT (プロンプト)              [コピー] │
│ ┌─────────────────────────────────┐   │
│ │ System: あなたは情報フィルタリン │   │
│ │ グの専門家です。以下のニュース記 │   │
│ │ 事を分析し、AIエージェント・機械 │   │
│ │ 学習・技術トレンドに関連する記事 │   │
│ │ を選別してください...            │   │
│ │                                 │   │
│ │ User: [収集データ 15件]          │   │
│ └─────────────────────────────────┘   │
├───────────────────────────────────────┤
│ OUTPUT (レスポンス)            [コピー] │
│ ┌─────────────────────────────────┐   │
│ │ {                               │   │
│ │   "relevant": [0,1,4,7,11],     │   │
│ │   "scores": [0.95,0.89,0.76...] │   │
│ │   "reason": "AI関連キーワード..."│   │
│ │ }                               │   │
│ └─────────────────────────────────┘   │
└───────────────────────────────────────┘
```

### 4.5 フッターバー — エラー / 警告

```
┌──────────────────────────────────────────────────────────────┐
│ ⚠️ 15:01:44  browse_source › newspicks — timeout (30s)        │
│ ℹ️ 15:00:12  PatrolScheduler — 非活動時間帯スキップ (01:00〜07:00) │
└──────────────────────────────────────────────────────────────┘
```

---

## 5. データソース仕様

### 5.1 SkillTrace JSON（読み取り元）

`data/traces/{YYYY-MM-DD}/{skill_name}/{trace_id}.json`

```json
{
  "trace_id": "a3f2c1b0-1234-5678-abcd-ef0123456789",
  "skill_name": "browse_source",
  "input_params": {
    "source_id": "hacker_news",
    "limit": 20
  },
  "status": "success",
  "started_at": "2026-04-01T06:03:42.123456+00:00",
  "finished_at": "2026-04-01T06:03:42.368000+00:00",
  "duration_ms": 245,
  "result_count": 15,
  "error": null,
  "extra": {
    "adapter": "hacker_news",
    "items_collected": 15
  }
}
```

LLM I/O トレース用の追加フィールド（`llm_call` Skill のみ）：

```json
{
  "extra": {
    "model": "qwen3.5-35b-a3b",
    "prompt_tokens": 412,
    "completion_tokens": 89,
    "tokens_per_second": 38.2,
    "prompt_text": "System: ...\n\nUser: ...",
    "response_text": "{\"relevant\": [0,1,4]}"
  }
}
```

### 5.2 Qdrant 統計（REST API）

```
GET http://qdrant:6333/collections
→ {
    "result": {
      "collections": [
        {"name": "episodic"},
        {"name": "semantic"},
        {"name": "procedural"}
      ]
    }
  }

GET http://qdrant:6333/collections/{name}
→ {
    "result": {
      "vectors_count": 1234,
      "points_count": 1234
    }
  }
```

### 5.3 スケジューラ状態（ファイル読み取り）

`data/scheduler/states.json`（PatrolScheduler が定期的に書き出す想定）

```json
{
  "updated_at": "2026-04-01T06:03:42+00:00",
  "sources": [
    {
      "source_id": "hacker_news",
      "enabled": true,
      "interval_min": 60,
      "last_run_at": "2026-04-01T05:23:00+00:00",
      "consecutive_failures": 0
    }
  ]
}
```

> 注意: PatrolScheduler の状態書き出し機能は Phase 2 ダッシュボード本実装時に追加する。
> POC 段階では patrol.yaml を読んでダミー表示する。

---

## 6. 表示パネル詳細

### 6.1 Skill カラーコーディング

| 状態 | 色 | アイコン | 説明 |
|------|----|---------|------|
| running | `#d29922`（amber） | 🔄 | 実行中（スピナーアニメーション） |
| success | `#3fb950`（green） | ✅ | 正常完了 |
| failure | `#f85149`（red） | ❌ | エラー終了 |
| pending | `#6e7681`（gray） | ⏳ | 待機中 |

### 6.2 Skill カテゴリアイコン

| Skill カテゴリ | アイコン | 色 |
|--------------|---------|-----|
| browse_source / fetch_rss | 🌐 | `#58a6ff`（blue） |
| llm_call | 🤖 | `#bc8cff`（purple） |
| store_episodic / store_semantic | 💾 | `#79c0ff`（light blue） |
| recall_related | 🔍 | `#56d364`（light green） |
| human_behavior | 🖱 | `#ffa657`（orange） |
| verify_x_session | 🐦 | `#1d9bf0`（X blue） |
| parse_llm_output / resolve_prompt | ⚙️ | `#b1bac4`（gray） |

### 6.3 所要時間の視覚化

```
~100ms   ██ （緑）
~500ms   ████████ （緑）
~1s      ████████████████ （黄）
~3s      ████████████████████████████████ （橙）
~10s+    ████████████████████████████████████ （赤、タイムアウト警告）
```

---

## 7. 技術スタック

### 7.1 バックエンド（dashboard server）

| コンポーネント | 採用技術 | 理由 |
|-------------|---------|------|
| Web フレームワーク | **FastAPI** | SSE ネイティブ対応、async、軽量 |
| ファイル監視 | **watchfiles** | Python製、`awatch()` で非同期ファイル監視 |
| Qdrant クライアント | **httpx** | REST API を直接叩く（qdrant-client は不要） |
| 設定読み込み | agent-core と共通の `utils/config.py` | コード重複なし |

### 7.2 フロントエンド

| コンポーネント | 採用技術 | 理由 |
|-------------|---------|------|
| フレームワーク | **Vanilla JS（ES2022）** | 依存ゼロ、1ファイル HTML で POC 可能 |
| リアルタイム更新 | **EventSource（SSE）** | WebSocket より軽量、HTTP/1.1 で動作 |
| スタイル | **CSS Grid + CSS Variables** | フレームワーク不要、ダークテーマ対応 |
| コードハイライト | **highlight.js（CDN）** | LLM I/O の JSON 表示用 |
| グラフ | **Chart.js（CDN）** | 軽量、Skill 実行頻度グラフ用 |

> Phase 2 本実装でフレームワーク（React / Svelte）への移行を検討する。POC 段階は Vanilla JS で十分。

---

## 8. 実装スケジュール

| Phase | タスク | 成果物 |
|-------|--------|--------|
| **今すぐ** | HTML POC | `dashboard/poc/monitor.html`（モックデータ表示） |
| **今すぐ** | 仕様書 | `docs/8_dashboard_spec.md`（本ファイル） |
| **Phase 2 開始時** | Dashboard 本実装 | `dashboard/` ディレクトリ一式 + Docker サービス追加 |
| **Phase 2 開始時** | PatrolScheduler 状態書き出し | `data/scheduler/states.json` の定期書き出し機能 |
| **Phase 3** | グラフ・統計ページ | Skill 実行統計・メモリ成長グラフ |

---

## 9. セキュリティ考慮

- ダッシュボードは **ローカルネットワーク専用**（外部公開しない）
- LLM プロンプトに含まれる個人情報・Cookie は表示時にマスキングする
- READ-ONLY 設計を維持し、Agent への書き込み API は実装しない
- Docker ネットワーク内部のみでアクセス（ポート 8080 は localhost にバインド）
