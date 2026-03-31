# Part 1: 計画書本体


## 1. プロジェクト概要

### 1.1 ビジョン

カスタマイズしたキャラクターを持つ AI Agent が、24 時間自律的に動作する。
X と Discord の両方に常駐し、Web ブラウジング・情報収集・アクション実行・知識の蓄積と学習を自律的に行う。
LLM が自ら次のアクションを判断し、Skill を選択して実行する「Skill-based Architecture」を採用する。

### 1.2 設計原則

| # | 原則 | 説明 |
|---|------|------|
| 1 | **Skill 単一責任** | 各 Skill は 1 つの機能に集中する。Skill をまたぐ状態共有は禁止 |
| 2 | **INPUT = YAML / OUTPUT = JSON** | 設定・プロファイル・タスク定義は全て YAML。実行結果・トレース・記憶は全て JSON |
| 3 | **段階的 Skill 選択** | Phase 1 はルールベーススケジューラ。Phase 2 以降で LLM 駆動に移行する |
| 4 | **観測可能性** | 全 Skill 実行に SkillTrace を付与。何を実行し、何件ヒットし、何 ms かかったかを記録 |
| 5 | **過設計禁止** | プラグインシステム・動的ロードは作らない。Skill は Python dataclass + 関数参照 |
| 6 | **常時存在** | X か Discord のどちらかには必ず Agent が存在している状態を維持する |
| 7 | **情報源の多層化** | X に依存しない。X / ニュースサイト / GitHub / HN / RSS を並列ソースとし、いずれが落ちても情報収集能力を維持する |
| 8 | **アダプタパターン** | 情報源は Skill ではなく YAML 設定（config/sources/）で追加する。共通基盤 + ソースアダプタで新サイト追加のコストを最小化 |

### 1.3 技術方針

| 項目 | 方針 |
|------|------|
| LLM バックエンド | ローカルのみ（Ollama or MLX + Qwen3.5 量子化モデル） |
| 実行環境 | Docker Compose（Agent 群） + ホスト直接実行（Ollama） |
| ブラウザ操作 | Playwright Stealth（bot 検出回避） — API 併用なし |
| 記憶・学習 | Qdrant（ベクトル DB） + 構造化メモリ（JSON） |
| 自律性 | 段階的自律（Phase 1: ルールベース巡回 → Phase 2+: LLM 自己判断） |
| ファイル規約 | INPUT: YAML / OUTPUT: JSON |

### 1.4 能力の優先順位

1. **Web 閲覧・情報収集**（X / ニュース / 技術サイト — ブラウザ操作のみ）
2. **Web アクション実行**（ボタンクリック・フォーム入力・ページ遷移）
3. **情報蓄積・長期記憶・学習**（RAG + 自己進化メモリ）
4. **キャラクター性のある対話・発信**（X 投稿 / Discord 応答）

---

## 2. 実現性評価

### 2.1 結論: 実現可能（条件付き）

各コンポーネントの OSS は成熟しており技術的には実現可能。
最大のリスクは「ローカル LLM のブラウザ推論品質」と「X の bot 検出回避」の 2 点。

### 2.2 コンポーネント別 実現性

#### ブラウザ自律操作（bot 検出回避含む） — ⚠️ 条件付き

- **Browser Use + Playwright**: LLM にブラウザの完全制御を委譲。Ollama バックエンド対応済み
- **X の現実（2026 年 2 月）**: プロダクト責任者 Nikita Bier が以下を明言
  - 「人間が画面をタップしていなければ、アカウントと関連アカウント全てを停止する」
  - 「自動化されたスクレイピングや検索は現在すべて検出される」
  - X は検索コードベースを bot 検出込みで全面書き換え中
- **対応方針**: X は「読取のみ（閲覧・スクロール）」に限定し、エンゲージメント自動化は一切行わない。情報収集は X に依存せず、ニュースサイト / GitHub / HN / RSS を並列ソースとして常に確保する
- **Stealth 多層化**: fingerprint 偽装 + 永続プロファイル + HumanBehavior Skill（Poisson 分布ベースの操作間隔、マウス軌跡の揺らぎ、生活リズム連動の活動時間帯制御）
- **リスク**: Python の `playwright-stealth` は Node.js 版より検出されやすい（GPU 情報の差異）。Phase 0 で X アクセスの実用性を検証し、Go / No-Go を判定する

#### ローカル LLM 推論 — ✅ 実現可能

- **Ollama / MLX**: ホスト直接実行で Apple Silicon Metal GPU を活用。Phase 0 でバックエンドを選定
- **Qwen3.5 系量子化モデル**: Gated DeltaNet hybrid アーキテクチャにより、35B パラメータでも活性 3B で高速推論。コンテキスト 262K トークン対応
- **リスク**: ブラウザ操作 1 ステップごとに LLM 推論が発生。レイテンシ蓄積が課題

#### 記憶・学習（RAG） — ✅ 実現可能

- **Qdrant**: Zethi/Prako で運用実績あり。階層チャンキング経験を直接活用
- **Mem0 / A-Mem 方式**: Write-Manage-Read ループで自己進化型メモリを実装可能
- **リスク**: メモリ肥大化によるリトリーバル精度低下

#### Skill-based Architecture — ✅ 実現可能

- Talkov-Chan プロジェクトの設計知見を直接応用
- SearchSkillSpec パターンを汎用化し、全 Skill カテゴリに拡張
- SkillTrace による実行経路の完全な可視化

### 2.3 リスクマトリクス

| リスク | 影響度 | 発生確率 | 対策 |
|--------|--------|----------|------|
| X の bot 検出・凍結 | 高 | **非常に高** | 読取限定 + Stealth 多層化 + 操作頻度制限。**X がダメでも Agent は死なない**（代替ソースで情報収集継続） |
| X アクセス自体が恒久的に不可能 | 中 | 中 | 代替ソース群（HN / GitHub / RSS / ニュースサイト）で情報収集能力を維持 |
| ローカル LLM の推論品質不足 | 高 | 中 | マルチモデル戦略 + Skill 難易度に応じたモデル切替 |
| ブラウザセッション切れ | 中 | 高 | 永続プロファイル + 手動再認証（VNC） + Dashboard 通知 |
| メモリ肥大化 | 中 | 中 | TTL + 重要度スコアリング + 定期圧縮 |
| 無限ループ・暴走 | 高 | 低 | Skill 実行上限 + サーキットブレーカー |

---

## 3. システムアーキテクチャ

### 3.1 全体構成（ホスト + Docker 分離）

Ollama は Docker 内では Apple Silicon GPU を利用できないため、ホスト直接実行とする。
Docker 内のコンテナは `host.docker.internal` 経由で Ollama に接続する。

```
┌─── Mac Host（M4 Pro / 48GB）─────────────────────────┐
│                                                       │
│  Ollama or MLX（ホスト直接実行）                         │
│  ├── Metal GPU アクセラレーション有効                    │
│  ├── Qwen3.5-35B-A3B（Gated DeltaNet, Q4_K_M）← メイン推論 │
│  ├── Qwen3.5-4B（Q8_0）← 軽量判断                     │
│  └── 埋め込みモデル（Phase 0 で選定）                    │
│  Port: 11434                                          │
│                                                       │
│  ┌─── Docker Compose ──────────────────────────────┐  │
│  │                                                 │  │
│  │  ┌─────────────────────────────────────────┐    │  │
│  │  │  agent-core（Python 3.12）               │    │  │
│  │  │  ├── Skill Engine（Skill選択・実行）      │    │  │
│  │  │  ├── Scheduler（自律行動スケジューラ）     │    │  │
│  │  │  ├── Memory Manager（記憶管理）           │    │  │
│  │  │  └── Character Engine（キャラクター）      │    │  │
│  │  │  → http://host.docker.internal:11434     │    │  │
│  │  └─────────────────────────────────────────┘    │  │
│  │                                                 │  │
│  │  ┌──────────────┐  ┌────────────┐              │  │
│  │  │  browser      │  │  qdrant    │              │  │
│  │  │  (Playwright  │  │  (6333)    │              │  │
│  │  │   Stealth +   │  └────────────┘              │  │
│  │  │   Chromium)   │                              │  │
│  │  │  (VNC: 5900)  │  ┌────────────┐              │  │
│  │  └──────────────┘  │  dashboard  │              │  │
│  │                     │  (8080)     │              │  │
│  │                     └────────────┘              │  │
│  └─────────────────────────────────────────────────┘  │
│         ▲                                             │
│    [Volume Mount]                                     │
│    ./data → /data                                     │
└───────────────────────────────────────────────────────┘
```

### 3.2 コンテナイメージ設計

| サービス | ベースイメージ | 内容 | ポート | リソース制限 |
|----------|---------------|------|--------|-------------|
| `agent-core` | `python:3.12-slim` | Skill Engine / Scheduler / Memory / Character | — | CPU: 4cores, Mem: 4GB |
| `browser` | `mcr.microsoft.com/playwright:v1.52.0-noble` | headless Chromium + Playwright Stealth + VNC | VNC: 5900 | CPU: 2cores, Mem: 3GB |
| `qdrant` | `qdrant/qdrant:latest` | ベクトル DB | 6333, 6334 | CPU: 2cores, Mem: 4GB |
| `dashboard` | `node:22-alpine` | 監視・ログ・手動制御 UI | 8080 | CPU: 1core, Mem: 512MB |

**ブラウザの分離**: Playwright を agent-core と別コンテナにすることで、ブラウザクラッシュ時の影響を隔離。agent-core は Playwright の CDP（Chrome DevTools Protocol）経由で browser コンテナに接続する。

### 3.3 コンテナ間通信

```
agent-core ──CDP──► browser (ws://browser:9222)
agent-core ──HTTP──► host.docker.internal:11434 (Ollama)
agent-core ──gRPC──► qdrant:6334
agent-core ──HTTP──► dashboard:8080 (WebSocket for logs)
```

### 3.4 リソース設計（Mac M4 Pro 48GB）

| コンポーネント | メモリ | 備考 |
|---------------|--------|------|
| Ollama（ホスト） | ~20GB | Qwen3.5-35B-A3B Q4_K_M: ~18GB + overhead |
| agent-core | 4GB | |
| browser | 3GB | Chromium + 複数タブ |
| qdrant | 4GB | |
| dashboard | 512MB | |
| **合計** | ~31.5GB | |
| **ホスト余裕** | ~16.5GB | macOS + 他アプリ |

---

## 4. Skill-based Architecture

### 4.1 設計思想

Talkov-Chan の Skill 概念を汎用化する。
Talkov-Chan では「検索 Skill の宣言的定義 + trace 付き実行ループ」が核心だったが、
本プロジェクトでは **LLM が自ら Skill を選択する** というレイヤーを追加する。

```
[Talkov-Chan]
  固定パイプライン → 全 Skill を順次実行 → 結果を集約

[本プロジェクト Phase 1]
  ルールベーススケジューラ → cron 的巡回で Skill を実行 → 結果を記憶に蓄積

[本プロジェクト Phase 2+]
  LLM が状況を分析 → 必要な Skill を動的に選択 → 実行 → 結果を評価 → 次の Skill を判断
```

### 4.2 SkillSpec 定義（YAML → dataclass）

全 Skill は YAML で定義し、起動時に Python dataclass にロードする。

```yaml
# config/skills/browse_x.yaml
name: browse_x
category: perception
description: "Xのタイムラインを閲覧し、指定トピックの投稿を収集する"
input_schema:
  topic: str
  max_posts: int
  scroll_depth: int
output_schema:
  posts: list[dict]
  collected_at: str
timeout_sec: 120
max_retries: 2
requires:
  - browser
  - stealth
priority: 10
```

```python
# core/skill_spec.py
@dataclass
class SkillSpec:
    name: str
    category: str        # perception / action / memory / reasoning / character
    description: str     # LLM が Skill を選ぶ際の説明文
    input_schema: dict
    output_schema: dict
    timeout_sec: int
    max_retries: int
    requires: list[str]  # 依存リソース
    priority: int
    func: Callable       # 実行関数（起動時にバインド）
```

### 4.3 Skill カタログ（Phase 別に拡張）

#### 統合 Perception — 情報収集（アダプタパターン）

| Skill 名 | 説明 | Phase |
|-----------|------|-------|
| `browse_source` | 共通基盤。config/sources/*.yaml で定義されたソースから情報を収集する統合 Skill | 1 |
| `fetch_rss` | RSS フィード取得・パース（ブラウザ不要。browse_source と分離） | 1 |

ソースアダプタ（config/sources/*.yaml で追加）:

| アダプタ | type | Stealth | Phase | 備考 |
|---------|------|---------|-------|------|
| yahoo_news | browser | 不要 | 1 | 常時稼働 |
| google_news | browser | 不要 | 1 | 常時稼働 |
| newspicks | browser | 不要 | 1 | 常時稼働 |
| hacker_news | api | 不要 | 1 | 常時稼働。Firebase API |
| github_trending | browser | 不要 | 1 | 常時稼働 |
| x_timeline | browser_stealth | 必要 | 1 | Phase 0 Go/No-Go 次第 |
| x_search | browser_stealth | 必要 | 1 | 1日5回上限 |
| reddit | browser | 不要 | 2 | Phase 2 で追加 |
| tech_blogs | browser | 不要 | 2 | Phase 2 で追加 |

**低レベルブラウザ操作（click_element / navigate_to / scroll_page）は独立 Skill ではなく、browse_source 内部のユーティリティ関数として実装する。**

#### Memory Skills — 記憶・学習

| Skill 名 | 説明 | Phase |
|-----------|------|-------|
| `store_episodic` | 行動ログを Episodic Memory に保存 | 1 |
| `store_semantic` | 抽出した知識を Semantic Memory に保存 | 1 |
| `recall_related` | 関連記憶を検索・取得 | 1 |
| `store_procedural` | 成功パターンを Procedural Memory に保存 | 2 |
| `compress_memory` | 古い記憶の圧縮・統合 | 3 |
| `forget_low_value` | 低重要度記憶の削除 | 3 |

#### Reasoning Skills — 推論・判断

| Skill 名 | 説明 | Phase |
|-----------|------|-------|
| `llm_call` | Ollama/MLX への統一リクエスト送信（モデル自動選択） | 1 |
| `parse_llm_output` | LLM 出力の JSON パース（2 段階フォールバック） | 1 |
| `resolve_prompt` | YAML テンプレートに変数を注入してプロンプト生成 | 1 |
| `select_skill` | 状況に応じて次に実行する Skill を LLM で選択 | **2** |
| `build_llm_context` | LLM 呼び出し前に Working Memory を組み立てる | **2** |
| `plan_task` | タスクを具体的なアクション列に分解 | **2** |
| `reflect` | 行動結果の振り返り・評価 | 2 |
| `evaluate_importance` | 情報の重要度スコアリング | 2 |
| `generate_goal` | 自律的な目標生成 | 3 |

#### Character Skills — キャラクター・対話

| Skill 名 | 説明 | Phase |
|-----------|------|-------|
| `build_persona_context` | キャラクター状態からプロンプト用コンテキスト生成 | 2 |
| `generate_response` | キャラクター性のある応答生成 | 2 |
| `update_emotion` | L3 感情状態の更新 | 3 |
| `update_character_state` | L2〜L5 の定期更新 | 3 |
| `maintain_presence` | X / Discord での存在感維持行動 | 3 |

#### Browser Meta Skills — ブラウザ制御

| Skill 名 | 説明 | Phase |
|-----------|------|-------|
| `human_behavior` | ブラウザ操作に人間的な揺らぎを付与するメタ Skill | 1 |
| `verify_x_session` | X のセッション有効性を確認する | 1 |

**Phase 1 Skill 総数: 10**（browse_source, fetch_rss, store_episodic, store_semantic, recall_related, llm_call, parse_llm_output, resolve_prompt, human_behavior, verify_x_session）
**全 Skill 総数: 28**（アダプタパターンによる統合で 38 → 28 に削減。ソース追加はアダプタ YAML で対応）
詳細定義は `3_skill_definition.md` + `4_llm_prompt_context.md` を参照。

### 4.4 Skill 選択フロー（段階的）

#### Phase 1: ルールベーススケジューラ

Agent は config/schedules/patrol.yaml に定義されたスケジュールに従い、cron 的に各ソースを巡回する。

```
[Agent 起動]
     │
     ▼
[config/schedules/patrol.yaml から巡回スケジュールをロード]
     │
     ▼
┌──► [Scheduler: 次の巡回タイミングを確認]
│    │
│    ├── hacker_news: 60分間隔
│    ├── rss_feeds: 60分間隔
│    ├── news_sites: 120分間隔
│    ├── github_trending: 360分間隔
│    └── x_timeline: 180分間隔（Phase 0 Go判定後に有効化）
│         │
│         ▼
│    [browse_source: ソースアダプタに従い情報収集]
│         │
│         ├── 成功 → SkillTrace（JSON）記録
│         │         → store_episodic に行動ログ保存
│         │         → store_semantic に知識保存
│         │
│         └── 失敗 → SkillTrace（JSON, error 付き）記録
│                   → リトライ or サーキットブレーカー
│         │
│         ▼
└──── [次のスケジュールへ]
```

#### Phase 2+: LLM 駆動

Agent は固定パイプラインではなく、LLM が状況を分析して Skill を動的に選択する。

```
[Scheduler: 次のタイムスロット到達]
     │
     ▼
[select_skill Skill 呼び出し]
  LLM への入力（YAML 形式）:
    current_state:
      time: "2026-03-31T14:00:00+09:00"
      last_action: "browse_source"
      last_action_result: "5 posts collected about AI agents"
      pending_goals:
        - "AI Agent の最新動向を追跡する"
        - "Discord でユーザーの質問に答える"
      memory_summary: "直近3時間でAI関連15件、Solana関連3件を収集"
      presence:
        x: "30分前に最終閲覧"
        discord: "10分前にメッセージ応答"
    available_skills:
      - name: browse_source
        description: "情報ソース巡回（アダプタ指定）"
      - name: send_discord
        description: "Discordメッセージ送信"
      # ... 全 Skill の name + description
     │
     ▼
  LLM の出力（JSON 形式）:
    {
      "selected_skill": "browse_source",
      "reason": "AI関連はXで十分収集済み。ニュースサイトで補完情報を取得する",
      "parameters": {
        "adapter": "google_news",
        "topic": "AI agents autonomous"
      }
    }
     │
     ▼
[Skill Engine: browse_source を実行]
     │
     ▼
[SkillTrace を JSON で記録]
     │
     ▼
[reflect Skill: 結果を評価 → 記憶に保存]
     │
     ▼
[次の select_skill ループへ]
```

### 4.5 SkillTrace 設計（JSON 出力）

```json
{
  "trace_id": "a3f2c1b0-xxxx",
  "agent": "agent_name",
  "timestamp": "2026-03-31T14:00:00+09:00",
  "skill": "browse_x_timeline",
  "input_summary": "topic=AI agents, max_posts=10",
  "result_count": 7,
  "duration_ms": 4200,
  "error": null,
  "context": {
    "selected_by": "select_skill",
    "reason": "定期巡回スケジュール"
  }
}
```

---

## 5. 記憶システム設計

### 5.1 3 層メモリアーキテクチャ

```
┌────────────────────────────────────────┐
│         Working Memory（揮発）          │
│  現在のタスクコンテキスト・LLM 入力       │
│  保持期間: 1 セッション                  │
└───────────────┬────────────────────────┘
                │ reflect Skill で抽出
                ▼
┌────────────────────────────────────────┐
│       Qdrant Collections（永続）        │
│                                        │
│  [episodic]  行動ログ・体験記録 — Phase 1 から │
│   payload: {timestamp, action, result, │
│             context, importance_score}  │
│   TTL: 30日（importance > 0.8 は永続）  │
│                                        │
│  [semantic]  抽出された知識・事実 — Phase 1 から │
│   payload: {topic, content, source,    │
│             confidence, extracted_at}   │
│   定期的に compress_memory で統合        │
│                                        │
│  [procedural] 成功パターン・手順 — Phase 2 から │
│   payload: {task_type, skill_sequence, │
│             success_rate, avg_duration} │
│   成功率が高いほど select_skill で優先   │
│                                        │
│  [character]  キャラクター関連記憶 — Phase 3 から │
│   payload: {interaction, user_id,      │
│             relationship, preference}   │
└────────────────────────────────────────┘
```

### 5.2 記憶の Write-Manage-Read ループ

- **Phase 1**: **Write-Read のみ**。Write で保存、Read で検索。TTL ベースの自動削除のみ
- **Phase 2**: Write-Read + 基本 Manage（store_procedural 追加）
- **Phase 3**: 完全な Write-Manage-Read（compress_memory, forget_low_value 追加）

1. **Write**: 行動後に `store_episodic` / `store_semantic` Skill が結果を評価し、`importance_score` 付きで JSON として記憶に保存
2. **Manage**: `compress_memory` Skill が定期的にメモリを走査。類似記憶の統合、低重要度記憶の TTL 期限切れ削除を実施（Phase 3 から）
3. **Read**: `recall_related` Skill がタスク実行前に関連記憶を検索し、Working Memory に注入

---

## 6. ファイル規約: INPUT = YAML / OUTPUT = JSON

### 6.1 YAML（入力・設定・定義）

| 用途 | パス | 例 |
|------|------|----|
| Skill 定義 | `config/skills/*.yaml` | browse_source.yaml, store_episodic.yaml |
| ソースアダプタ | `config/sources/*.yaml` | yahoo_news.yaml, hacker_news.yaml |
| 巡回スケジュール | `config/schedules/patrol.yaml` | 巡回間隔定義 |
| キャラクタープロファイル | `config/characters/*.yaml` | agent_character.yaml |
| スケジュール定義 | `config/schedules/*.yaml` | daily_routine.yaml |
| 目標定義 | `config/goals/*.yaml` | default_goals.yaml |
| Stealth 設定 | `config/browser/stealth.yaml` | fingerprint, timing 設定 |
| 環境設定 | `config/settings.yaml` | Ollama URL, Qdrant URL 等 |

### 6.2 JSON（出力・ログ・記憶）

| 用途 | パス | 例 |
|------|------|----|
| SkillTrace | `data/traces/YYYY-MM-DD.jsonl` | 1 行 1 Skill 実行 |
| PipelineTrace | `data/pipelines/YYYY-MM-DD.jsonl` | 1 行 1 タスク全体 |
| 記憶書き込み | Qdrant payload | JSON 形式 |
| Skill 実行結果 | メモリ内 / ログ | 全て JSON |
| Dashboard 通信 | WebSocket | JSON メッセージ |

---

## 7. X アクセス戦略 + 情報源の多層化

### 7.1 X bot 検出の現実（2026 年 2〜3 月）

2026 年 2 月、X のプロダクト責任者 Nikita Bier が以下を明言した。

- 「人間が画面をタップしていなければ、アカウントと関連アカウント全てを停止する。実験目的であっても同様」
- 「自動化されたスクレイピングや検索は現在すべて検出される」
- X は検索コードベースを bot 検出込みで全面書き換え中

X の検出は 6 層構造で、fingerprint 偽装だけでは突破できない。

| レイヤー | 検出対象 | 突破難易度 |
|----------|---------|-----------|
| L1: デバイス Fingerprint | webdriver / WebGL / Canvas / フォント | 中 |
| L2: ブラウザ環境 | CDP 接続検出 / SwiftShader / headless | 高 |
| L3: トラフィック | TLS fingerprint / IP 属性 / リクエストタイミング | 高 |
| L4: 行動分析 | マウス軌跡 / クリック間隔 / スクロール速度 | **最高** |
| L5: コンテンツ分析 | 投稿パターン / エンゲージメント相関 / ネットワーク | **最高** |
| L6: セッション整合性 | Cookie 一貫性 / TZ・言語の矛盾 | 中 |

### 7.2 根本方針: 読取/書込の完全分離

| 操作 | リスク | 方針 |
|------|--------|------|
| タイムライン閲覧（スクロール） | 中 | **Phase 1 でやる** — パッシブ操作。Stealth + HumanBehavior で対処 |
| 投稿の個別閲覧 | 低〜中 | **Phase 1 でやる** — 通常のブラウジング行動 |
| 検索 | **高** | **極端に制限**（1 日 5 回 / 最低 60 分間隔） — Bier が検出を明言 |
| いいね / RT / フォロー | **最高** | **やらない** — 自動エンゲージメントは即停止対象 |
| 投稿 / リプライ | 高 | **Phase 3 以降で判断** — Bot ラベルアカウント + 手動承認フロー等を検討 |

### 7.3 多層 Stealth 構成

| レイヤー | 対策 | 実装 |
|----------|------|------|
| **L1: Fingerprint** | navigator.webdriver 除去、WebGL/Canvas ノイズ | `rebrowser-playwright` + カスタム init script |
| **L2: Browser Profile** | 永続プロファイル（Cookie/LS/セッション） | Chrome user-data-dir のボリュームマウント |
| **L3: 行動パターン** | 人間的操作（マウス揺らぎ、Poisson 間隔、スクロール変動） | `human_behavior` Skill（YAML 定義） |
| **L4: 時間パターン** | 生活リズム連動（朝・昼・夜の活動重み） | Scheduler の `daily_active_hours` 設定 |
| **L5: セッション管理** | 手動初回ログイン → 永続化、切れたら VNC 通知 | `verify_x_session` Skill |
| **L6: 操作頻度制限** | 1 日最大 6 セッション / 各最長 45 分 / セッション間休憩 | `config/safety_x.yaml` |

### 7.4 HumanBehavior Skill（概要）

ブラウザ操作に人間的な揺らぎを付与するメタ Skill。詳細は `2_x_browser_strategy.md` に記載。

```yaml
# config/skills/human_behavior.yaml — 主要パラメータ
parameters:
  mouse:
    algorithm: bezier_with_perturbation  # 完璧な曲線を避ける
    overshoot_probability: 0.08          # 8%でターゲット通り過ぎ
  scroll:
    pattern: variable_with_pauses        # 読書行動をシミュレート
    reverse_probability: 0.05            # 5%で少し戻る
  timing:
    action_interval:
      distribution: poisson
      lambda_sec: 5.0                    # 平均5秒間隔
    session_duration:
      max_min: 45                        # 最長45分/セッション
    daily_active_hours:
      active_ranges:
        - { start: "07:00", end: "09:00", weight: 0.7 }
        - { start: "12:00", end: "13:00", weight: 0.5 }
        - { start: "18:00", end: "23:00", weight: 1.0 }
      inactive_ranges:
        - { start: "02:00", end: "06:00" }  # 操作しない
```

### 7.5 検出時の段階的対応

```
CAPTCHA 出現    → 即時停止 → 6時間クールダウン → 頻度50%低減
レート制限      → 2時間停止 → 通知
アカウントロック → 全操作停止 → 人間がVNCで解決するまで待機
アカウント停止  → 緊急全停止 → 別アカウントへの自動切替はしない（連鎖停止リスク）
```

### 7.6 情報源の多層化（フォールバック設計）

**X は情報源の 1 つにすぎない。** Agent の情報収集能力を X だけに依存させない。
X がブロックされても、他のソースで情報収集を継続する。

```
情報収集アーキテクチャ:

┌─────────────────────────────────────────────────┐
│              Information Source Layer             │
│                                                 │
│  ┌─────────┐ ┌─────────┐ ┌────────┐ ┌────────┐ │
│  │    X     │ │  News   │ │ GitHub │ │  RSS   │ │
│  │(Stealth)│ │  Sites  │ │Trending│ │ Feeds  │ │
│  │ risk:高  │ │ risk:低 │ │ risk:低│ │risk:無 │ │
│  └────┬────┘ └────┬────┘ └───┬────┘ └───┬────┘ │
│       │          │          │          │       │
│  ┌────┴──────────┴──────────┴──────────┴────┐  │
│  │         Perception Skills 統合レイヤー     │  │
│  │   ソースに関係なく統一フォーマット(JSON)で   │  │
│  │   Semantic Memory に保存                  │  │
│  └───────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

| ソース | 取得方法 | Stealth 必要 | リスク | 情報の質 | 常時稼働 |
|--------|---------|-------------|--------|---------|---------|
| **X** | Playwright Stealth | 必要 | 高 | 高（リアルタイム） | Phase 0 で判定 |
| **ニュースサイト** | Playwright（通常） | 不要 | 低 | 高（一次ソース） | **常時** |
| **Hacker News** | Firebase API（公式） | 不要 | なし | 高（技術コミュニティ） | **常時** |
| **GitHub Trending** | Playwright（通常） | 不要 | 低 | 高（技術トレンド） | **常時** |
| **RSS フィード** | 直接取得（ブラウザ不要） | 不要 | なし | 中 | **常時** |
| **Reddit** | Playwright / API | 低 | 低〜中 | 中〜高 | Phase 2 で追加 |

```yaml
# config/information_sources.yaml

sources:
  # --- 常時稼働ソース（X の状態に関係なく動作）---
  - name: hacker_news
    type: api
    url: "https://hacker-news.firebaseio.com/v0/"
    adapter: hacker_news
    frequency_min: 60
    stealth_required: false
    always_active: true

  - name: github_trending
    type: browser
    url: "https://github.com/trending"
    adapter: github_trending
    frequency_min: 360
    stealth_required: false
    always_active: true

  - name: rss_feeds
    type: rss
    adapter: fetch_rss
    frequency_min: 60
    stealth_required: false
    always_active: true
    feeds:
      - url: "https://feeds.feedburner.com/TechCrunch"
        category: tech
      - url: "https://www.theverge.com/rss/index.xml"
        category: tech
      - url: "https://hnrss.org/frontpage"
        category: tech_community

  - name: news_sites
    type: browser
    adapter: yahoo_news
    frequency_min: 120
    stealth_required: false
    always_active: true
    sites:
      - url: "https://techcrunch.com"
        category: tech
      - url: "https://www.theverge.com"
        category: tech

  # --- X（条件付き稼働）---
  - name: x_timeline
    type: browser_stealth
    adapter: x_timeline
    frequency_min: 180           # 3時間に1回
    stealth_required: true
    always_active: false         # Phase 0 の結果次第
    daily_limits:
      max_sessions: 6
      max_scrolls: 100
      max_searches: 5
    fallback_on_failure:
      action: disable_and_notify
      increase_other_sources: true  # X 停止時は他ソースの頻度を上げる

# X がダメになった場合の自動調整
fallback_policy:
  trigger: x_unavailable_24h     # 24時間X不通で発動
  actions:
    - increase_frequency:
        hacker_news: 30          # 60分 → 30分に
        news_sites: 60           # 120分 → 60分に
        github_trending: 180     # 360分 → 180分に
    - add_source:
        name: reddit
        type: browser
        url: "https://www.reddit.com/r/technology/top/?t=day"
        frequency_min: 120
```

### 7.7 Phase 0 における X 検証の Go / No-Go

| # | 検証項目 | 合格基準 |
|---|---------|---------|
| 1 | bot.sannysoft.com 全テスト通過 | 全項目 green |
| 2 | browserscan.net CDP 検出回避 | "No automation detected" |
| 3 | X セッション維持（手動ログイン後） | 24 時間後もセッション有効 |
| 4 | X タイムライン閲覧（10 回試行） | 8/10 回成功 |
| 5 | X 検索（5 回試行） | 3/5 回成功 |
| 6 | 72 時間連続運用テスト | アカウント停止なし |

| 結果 | 判定 | 次のアクション |
|------|------|--------------|
| 6/6 通過 | **Go** | X を含む全ソースで Phase 1 |
| 4-5/6 通過 | **条件付き** | X は低頻度運用 + 代替ソース強化 |
| 1-3/6 通過 | **X 断念** | X 以外のソースに集中。Agent の価値は X なしでも成立する |
| アカウント停止 | **戦略転換** | Bot ラベル + API 方式を検討、またはX自体を対象外に |

---

## 8. LLM モデル戦略

### 8.1 マルチモデル構成

| 用途 | モデル | パラメータ | 量子化 | VRAM | 想定速度 |
|------|--------|-----------|--------|------|----------|
| 推論（メイン） | **Qwen3.5-35B-A3B** | 35B（活性 3B） | Q4_K_M | ~18GB | MLX: 60-70 tok/s, Ollama: ~35 tok/s |
| 文章生成・分析 | Qwen3.5-14B | 14B | Q4_K_M | ~8GB | 中程度 |
| 軽量判断 | Qwen3.5-4B | 4B | Q8_0 | ~4GB | 非常に高速 |
| 埋め込み生成 | **Phase 0 で選定** | — | — | ~0.3-1.1GB | 高速 |

### 8.2 バックエンド選択（D2）

| バックエンド | 速度 | メリット | デメリット |
|------------|------|---------|-----------|
| Ollama | ~35 tok/s | エコシステム成熟、Docker連携容易 | 速度が遅い |
| MLX | 60-70+ tok/s | 高速、Apple最適化 | Docker連携が複雑 |

Phase 0 で検証し判定。

### 8.3 モデル切替戦略

LLM 呼び出しを `llm_call` Skill として統一し、タスクの重さに応じてモデルを自動選択する。

```yaml
# config/llm_routing.yaml
routing_rules:
  - condition: "skill_selection"
    model: qwen3.5-35b-a3b
    reason: "Skill選択は推論品質が最重要"
  - condition: "simple_classification"
    model: qwen3.5-4b
    reason: "Yes/No判断は軽量モデルで十分"
  - condition: "text_generation"
    model: qwen3.5-14b
    reason: "文章生成は中型モデルでバランス"
  - condition: "embedding"
    model: phase0_selected
    reason: "埋め込みはPhase 0 で選定した専用モデル"
```

### 8.4 最適化

- **KV キャッシュ**: `OLLAMA_NUM_CTX=16384`（8192 → 16384 に拡張。Qwen3.5 は 262K サポート）
- **モデルロード管理**: `OLLAMA_KEEP_ALIVE=10m` で使用後 10 分でアンロード、メモリ解放
- **同時推論防止**: agent-core 側で推論キューを実装し、Ollama への同時リクエストを 1 に制限

---

## 9. 自律行動ループ

### 9.1 メインループ

#### Phase 1: ルールベースループ

```
[Agent 起動]
     │
     ▼
[config/schedules/patrol.yaml から巡回スケジュールをロード]
     │
     ▼
┌──► [Scheduler: 次の巡回タイミングを確認]
│    │
│    ├── hacker_news: 60分間隔
│    ├── rss_feeds: 60分間隔
│    ├── news_sites: 120分間隔
│    ├── github_trending: 360分間隔
│    └── x_timeline: 180分間隔（Phase 0 Go判定後に有効化）
│         │
│         ▼
│    [browse_source: ソースアダプタに従い情報収集]
│         │
│         ├── 成功 → SkillTrace（JSON）記録
│         │         → store_episodic に行動ログ保存
│         │         → store_semantic に知識保存
│         │
│         └── 失敗 → SkillTrace（JSON, error 付き）記録
│                   → リトライ or サーキットブレーカー
│         │
│         ▼
└──── [次のスケジュールへ]
```

#### Phase 2+: LLM 駆動ループ

```
[Agent 起動]
     │
     ▼
[config/*.yaml から Skill / Schedule / Character をロード]
     │
     ▼
┌──► [Scheduler: 次のアクションタイミングを決定]
│    │
│    ▼
│    [select_skill: LLM が状況を分析し Skill を選択]
│    │
│    ├── 入力: current_state（YAML 形式）
│    │        + available_skills（description 一覧）
│    │        + recent_memory（直近の行動・記憶）
│    │
│    └── 出力: selected_skill + parameters（JSON）
│         │
│         ▼
│    [Skill Engine: 選択された Skill を実行]
│         │
│         ├── 成功 → SkillTrace（JSON）記録
│         │         → store_episodic に結果保存
│         │         → reflect で振り返り
│         │
│         └── 失敗 → SkillTrace（JSON, error 付き）記録
│                   → リトライ判断
│                   → サーキットブレーカー評価
│         │
│         ▼
│    [presence 確認]
│    ├── X に 30 分以上アクセスなし → 次は X 関連 Skill を優先
│    └── Discord に 15 分以上応答なし → Discord 監視を優先
│         │
│         ▼
└──── [次のループへ]
```

### 9.2 安全機構

| 機構 | 内容 | 設定ファイル |
|------|------|-------------|
| **Skill 実行上限** | 1 タスクあたり最大 50 Skill 呼び出し | `config/safety.yaml` |
| **タイムアウト** | Skill ごとに `timeout_sec` を YAML で定義 | 各 Skill YAML |
| **サーキットブレーカー** | 同一 Skill が連続 5 回失敗で 1 時間凍結 | `config/safety.yaml` |
| **リソースガード** | CPU 80% / Mem 90% 超で新規 Skill 実行抑止 | Docker cgroup |
| **ブラックリスト** | 操作禁止 URL / アクション | `config/safety.yaml` |
| **全ログ記録** | 全 SkillTrace を JSONL に永続記録 | `data/traces/` |

---

## 10. 常時存在（X + Discord デュアルプレゼンス）

### 10.1 プレゼンスモデル

Agent は X と Discord の両方に常駐し、少なくともどちらかには常にアクティブな状態を維持する。

```yaml
# config/presence.yaml
presence:
  x:
    min_activity_interval_min: 30    # 30分以上無活動なら優先的にX操作
    activities:
      - browse_timeline
      - like_relevant_post
      - post_insight                  # 収集した知識から投稿生成
      - reply_to_mention
  discord:
    min_activity_interval_min: 15    # 15分以上無応答なら優先的にDiscord
    activities:
      - monitor_channels
      - respond_to_mention
      - share_discovery               # Xで見つけた情報をDiscordで共有
```

### 10.2 クロスプラットフォーム知識共有

```
X で収集した情報 → Semantic Memory に保存（JSON）
                        │
                        ▼
              Discord で質問された時に recall_related で検索
                        │
                        ▼
              キャラクターとして応答 + 出典（X での発見）を付記
```

---

## 11. アウトプット設計

Agent が蓄積した知識・活動から、どのようなアウトプットを生成するかの設計。

### 11.1 自動生成アウトプット

| アウトプット | 説明 | 頻度 | 配信先 |
|-------------|------|------|--------|
| **Daily Digest** | 1 日の収集情報・活動サマリー | 毎日 | Discord / Dashboard |
| **Topic Report** | 特定トピックの深掘りレポート | 蓄積が閾値超過時 | Discord / Markdown ファイル |
| **Trend Alert** | 急上昇トピック・異常値の通知 | リアルタイム | Discord / Dashboard |
| **X 投稿** | 収集知識からキャラクターとして発信 | 1 日数回 | X |
| **Learning Log** | 新しく学習した知識の一覧 | 毎日 | Dashboard / JSONL |

### 11.2 リクエスト応答型アウトプット

| アウトプット | 説明 | トリガー | 配信先 |
|-------------|------|----------|--------|
| **質問応答** | ユーザーの質問にキャラクターとして回答 | Discord / X メンション | Discord / X |
| **調査レポート** | 指定トピックの深掘り調査 | ユーザー指示 | Discord / Markdown |
| **比較分析** | 複数トピックの比較表生成 | ユーザー指示 | Discord / Dashboard |

### 11.3 メタアウトプット（自己分析）

| アウトプット | 説明 | 頻度 |
|-------------|------|------|
| **Skill 実行統計** | 各 Skill の実行回数・成功率・平均所要時間 | 毎日（Dashboard） |
| **記憶成長グラフ** | Qdrant コレクション別のドキュメント数推移 | 毎日（Dashboard） |
| **行動パターン分析** | 自律行動の傾向（何をよくやっているか） | 週次 |
| **精度改善レポート** | Procedural Memory による成功率改善の追跡 | 週次 |

---

## 12. ディレクトリ構成

```
agentarium/
├── docker-compose.yml
├── .env
│
├── config/                          # INPUT: 全て YAML
│   ├── settings.yaml                # 環境設定（Ollama URL等）
│   ├── safety.yaml                  # 安全機構設定
│   ├── safety_x.yaml                # X操作専用の安全設定
│   ├── information_sources.yaml     # 情報源定義（X / HN / GitHub / RSS / News）
│   ├── presence.yaml                # X/Discord プレゼンス設定
│   ├── llm_routing.yaml             # LLM モデル切替ルール
│   ├── llm_context_limits.yaml      # コンテキスト長上限設定
│   ├── skills/                      # Skill 定義
│   │   ├── browse_source.yaml
│   │   ├── fetch_rss.yaml
│   │   ├── store_episodic.yaml
│   │   ├── recall_related.yaml
│   │   ├── llm_call.yaml
│   │   ├── resolve_prompt.yaml
│   │   ├── human_behavior.yaml
│   │   └── ...
│   ├── sources/                     # ソースアダプタ定義
│   │   ├── yahoo_news.yaml
│   │   ├── google_news.yaml
│   │   ├── newspicks.yaml
│   │   ├── hacker_news.yaml
│   │   ├── github_trending.yaml
│   │   ├── x_timeline.yaml
│   │   └── x_search.yaml
│   ├── characters/                  # キャラクター定義
│   │   └── agent_character.yaml     # 6層心理フレームワーク
│   ├── schedules/                   # スケジュール定義
│   │   ├── patrol.yaml              # 巡回スケジュール（Phase 1）
│   │   └── daily_routine.yaml
│   ├── goals/                       # 目標定義
│   │   └── default_goals.yaml
│   └── browser/                     # ブラウザ Stealth 設定
│       └── stealth.yaml
│
├── agent-core/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── src/
│   │   ├── main.py                  # エントリーポイント
│   │   │
│   │   ├── core/                    # パイプライン基盤
│   │   │   ├── skill_spec.py        # SkillSpec dataclass
│   │   │   ├── skill_engine.py      # Skill ロード・実行エンジン
│   │   │   ├── skill_trace.py       # SkillTrace / PipelineTrace
│   │   │   └── safety.py            # サーキットブレーカー・リソースガード
│   │   │
│   │   ├── skills/                  # Skill 実装
│   │   │   ├── perception/          # 知覚系
│   │   │   │   ├── browse_source.py
│   │   │   │   └── fetch_rss.py
│   │   │   ├── memory/              # 記憶系
│   │   │   │   ├── episodic.py
│   │   │   │   ├── semantic.py
│   │   │   │   ├── procedural.py
│   │   │   │   └── memory_manager.py
│   │   │   ├── reasoning/           # 推論系
│   │   │   │   ├── llm_call.py
│   │   │   │   ├── parse_output.py
│   │   │   │   ├── skill_selector.py
│   │   │   │   ├── task_planner.py
│   │   │   │   └── reflector.py
│   │   │   ├── character/           # キャラクター系
│   │   │   │   ├── persona.py
│   │   │   │   ├── emotion.py
│   │   │   │   └── response_gen.py
│   │   │   └── browser/             # ブラウザ Stealth 系
│   │   │       ├── stealth.py
│   │   │       ├── human_behavior.py
│   │   │       └── session_manager.py
│   │   │
│   │   ├── adapters/                # ソースアダプタ実装
│   │   │   ├── base.py              # アダプタ基底クラス
│   │   │   ├── hacker_news.py
│   │   │   ├── github_trending.py
│   │   │   ├── yahoo_news.py
│   │   │   ├── google_news.py
│   │   │   ├── newspicks.py
│   │   │   ├── x_timeline.py
│   │   │   └── x_search.py
│   │   │
│   │   ├── scheduler/               # スケジューラ
│   │   │   ├── cron_scheduler.py
│   │   │   └── presence_monitor.py
│   │   │
│   │   ├── models/                  # データモデル（dataclass）
│   │   │   ├── skill.py
│   │   │   ├── memory.py
│   │   │   ├── trace.py
│   │   │   └── llm.py
│   │   │
│   │   └── utils/
│   │       ├── yaml_loader.py       # YAML → dataclass 変換
│   │       ├── json_writer.py       # JSON / JSONL 出力ユーティリティ
│   │       └── llm_client.py        # LLM HTTP クライアント（Ollama / MLX 対応）
│   │
│   └── tests/
│       ├── test_skill_engine.py
│       ├── test_trace.py
│       ├── test_memory.py
│       └── test_human_behavior.py
│
├── browser/
│   └── Dockerfile                   # Playwright + Stealth 環境
│
├── dashboard/
│   ├── Dockerfile
│   └── src/
│
├── data/                            # OUTPUT: 全て JSON
│   ├── traces/                      # SkillTrace JSONL
│   ├── pipelines/                   # PipelineTrace JSONL
│   ├── qdrant/                      # Qdrant 永続化
│   ├── browser-profile/             # ブラウザプロファイル永続化
│   ├── outputs/                     # 生成レポート等
│   │   ├── daily-digest/
│   │   ├── topic-reports/
│   │   └── trend-alerts/
│   └── logs/                        # アプリケーションログ
│
└── docs/
    ├── 0_index.md                       # 設計書目次
    ├── 1_plan.md                        # 計画書本体（本ファイル）
    ├── 2_x_browser_strategy.md          # X ブラウザアクセス戦略
    ├── 3_skill_definition.md            # Skill 定義 + YAML テンプレート
    ├── 4_llm_prompt_context.md          # LLM プロンプト / コンテキスト管理
    ├── 5_character_framework.md         # キャラクターフレームワーク
    └── 6_decisions.md                   # 設計レビュー・意思決定ログ
```

---

## 13. 実装フェーズ

### Phase 0: 技術検証（1〜2 週間）

**前半（1 週目）: コアパイプライン検証**
- [ ] Qwen3.5-35B-A3B の推論速度・JSON 出力品質を計測
- [ ] Ollama vs MLX ベンチマーク（M4 Pro でのスループット比較）
- [ ] 埋め込みモデル日本語品質検証（nomic-embed-text vs multilingual-e5-base）
- [ ] SkillSpec YAML → dataclass ロードの基盤実装
- [ ] Qdrant 基本パイプライン（保存・検索）
- [ ] 代替ソース検証（HN Firebase API / GitHub Trending / RSS パイプライン）

**後半（2 週目）: ブラウザ・X 検証**
- [ ] Docker 内 Playwright Stealth テスト（bot.sannysoft.com / browserscan.net）
- [ ] X セッション維持テスト（手動ログイン後 24 時間）
- [ ] X タイムライン閲覧テスト（10 回試行、8/10 合格）
- [ ] X 72 時間連続運用テスト
- [ ] **Go / No-Go 判定**

**判定基準**:

| 結果 | 判定 | 次のアクション |
|------|------|--------------|
| X 検証 + LLM 速度 全合格 | **Go** | X を含む全ソースで Phase 1 |
| X 不安定だが LLM/代替ソースは OK | **条件付き** | X は低頻度運用 + 代替ソースを主軸に Phase 1 |
| X アカウント停止 | **X 断念** | 代替ソースのみで Phase 1。Agent は X なしでも成立する |
| LLM 推論が遅すぎる | **モデル見直し** | より小さいモデルを検証、またはタスク分割の設計変更 |

### Phase 1: 情報収集 Agent（1.5〜2 週間）

**目的**: ソースアダプタ + ルールベース巡回による自律情報収集ループを完成させる

- [ ] docker-compose.yml 完成（agent-core, browser, qdrant）
- [ ] core/skill_engine.py: YAML → SkillSpec ロード + 実行エンジン
- [ ] core/skill_trace.py: SkillTrace → JSONL 出力
- [ ] browse_source Skill 実装（共通基盤）
- [ ] ソースアダプタ実装: hacker_news, github_trending, yahoo_news, google_news, newspicks
- [ ] fetch_rss Skill 実装
- [ ] ソースアダプタ実装（X — Phase 0 結果次第）: x_timeline, x_search + human_behavior
- [ ] Memory Skills 実装: store_episodic, store_semantic（Qdrant 2 コレクション + TTL）, recall_related
- [ ] Reasoning Skills 実装: llm_call, parse_llm_output, resolve_prompt
- [ ] ルールベーススケジューラ（config/schedules/patrol.yaml に基づく cron 巡回）
- [ ] キャラクター L1 + L6 の静的 YAML 定義

**Skill 数: 10**
**成果物**: 複数の情報源を自律巡回し、情報を Qdrant に蓄積する Agent。X がなくても動く。

### Phase 2: LLM 駆動 + キャラクター + Discord（3〜4 週間）

**目的**: LLM 駆動の Skill 選択とキャラクター性の実装

- [ ] select_skill（LLM 駆動）, build_llm_context, plan_task の実装
- [ ] ルールベース → LLM 駆動スケジューラへの移行
- [ ] Memory Skills 拡充: store_procedural（Qdrant procedural コレクション追加）
- [ ] Reasoning Skills: reflect, evaluate_importance
- [ ] Character Skills: build_persona_context, generate_response
- [ ] キャラクター L2（Motivation）追加、L6 に platform_adaptations 追加
- [ ] Action Skills: send_discord（Discord 連携）
- [ ] 安全機構の完全実装（サーキットブレーカー、リソースガード）
- [ ] Dashboard UI 基盤

**Skill 数: +8 = 18**

### Phase 3: 完全自律 + 感情・疲労 + デュアルプレゼンス（3〜4 週間）

- [ ] Reasoning Skills: generate_goal（自律目標生成）
- [ ] Action Skills: post_x, reply_x（X での発信）
- [ ] Character Skills: update_emotion, update_character_state, maintain_presence
- [ ] キャラクター L3（感情）, L4（疲労）, L5（信頼）追加
- [ ] Qdrant character コレクション追加
- [ ] Memory Skills: compress_memory, forget_low_value
- [ ] Presence Monitor 完全実装
- [ ] アウトプット生成: Daily Digest, Topic Report, Trend Alert
- [ ] 長時間稼働テスト

**Skill 数: +10 = 28**

### Phase 4: 発展・最適化（継続的）

- [ ] Big Five 性格ドリフト有効化（月最大 5%）
- [ ] GraphRAG 導入（知識グラフ）
- [ ] Zethi / Prako との連携（マルチエージェント）
- [ ] VOICEVOX 連携（音声出力対応）
- [ ] 新モデル検証・移行

---

## 14. 既存資産の活用

| 既存資産 | 活用先 |
|----------|--------|
| Zethi/Prako Discord Agent | エージェントループ設計、Discord bot 基盤 |
| Talkov-Chan Skill Architecture | SkillSpec / SkillTrace 設計パターン |
| Qdrant + 埋め込みモデル（Phase 0 で選定） | 記憶システム（階層チャンキング経験） |
| 6 層心理フレームワーク | キャラクタープロファイル設計 |
| ConoHa VPS + Docker 運用 | Docker Compose 構成、永続化設計 |
| AITuber（Ollama + VOICEVOX） | ローカル LLM 運用ノウハウ |

---

## 15. 次のアクション

設計は全 5 Part + レビュー（6_decisions.md）が完了。Phase 0 の実装準備に移行する。

| # | 設計ブロック | 成果物 | ステータス |
|---|-------------|--------|-----------|
| 1 | X ブラウザアクセス戦略 | `2_x_browser_strategy.md` | ✅ 完了 |
| 2 | Skill 定義 + YAML テンプレート | `3_skill_definition.md` | ✅ 完了 |
| 3 | LLM プロンプト / コンテキスト管理 | `4_llm_prompt_context.md` | ✅ 完了 |
| 4 | キャラクターフレームワーク | `5_character_framework.md` | ✅ 完了 |
| 5 | 設計レビュー・意思決定 | `6_decisions.md` | ✅ 完了（D1-D11） |

次のステップ: Phase 0（技術検証）の環境構築

---
