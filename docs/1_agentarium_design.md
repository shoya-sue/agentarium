# Agentarium — 統合設計書

**リポジトリ名**: `agentarium`
**プロジェクト名**: Agentarium — Autonomous Personal Agent
**系譜**: Zethi / Prako Discord Agent → 発展型
**作成日**: 2026-03-31
**ステータス**: 設計策定（全 4 設計ブロック完了）

---

## 目次

### Part 1: 計画書本体
- 1. プロジェクト概要
- 2. 実現性評価
- 3. システムアーキテクチャ
- 4. Skill-based Architecture
- 5. 記憶システム設計
- 6. ファイル規約
- 7. X アクセス戦略 + 情報源の多層化
- 8. LLM モデル戦略
- 9. 自律行動ループ
- 10. 常時存在（X + Discord デュアルプレゼンス）
- 11. アウトプット設計
- 12. ディレクトリ構成
- 13. 実装フェーズ
- 14. 既存資産の活用
- 15. 次のアクション

### Part 2: X ブラウザアクセス戦略 詳細設計
### Part 3: Skill 定義 + YAML テンプレート 詳細設計
### Part 4: LLM プロンプト / コンテキスト管理 詳細設計
### Part 5: キャラクターフレームワーク 詳細設計

---
---

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
| 3 | **LLM 駆動の Skill 選択** | Agent が自ら状況を判断し、利用する Skill を動的に選択する |
| 4 | **観測可能性** | 全 Skill 実行に SkillTrace を付与。何を実行し、何件ヒットし、何 ms かかったかを記録 |
| 5 | **過設計禁止** | プラグインシステム・動的ロードは作らない。Skill は Python dataclass + 関数参照 |
| 6 | **常時存在** | X か Discord のどちらかには必ず Agent が存在している状態を維持する |
| 7 | **情報源の多層化** | X に依存しない。X / ニュースサイト / GitHub / HN / RSS を並列ソースとし、いずれが落ちても情報収集能力を維持する |

### 1.3 技術方針

| 項目 | 方針 |
|------|------|
| LLM バックエンド | ローカルのみ（Ollama + Qwen3 量子化モデル） |
| 実行環境 | Docker Compose（Agent 群） + ホスト直接実行（Ollama） |
| ブラウザ操作 | Playwright Stealth（bot 検出回避） — API 併用なし |
| 記憶・学習 | Qdrant（ベクトル DB） + 構造化メモリ（JSON） |
| 自律性 | 完全自律（24h LLM 自己判断で Skill を選択・実行） |
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

- **Ollama**: ホスト直接実行で Apple Silicon Metal GPU を活用
- **Qwen3 系量子化モデル**: MoE アーキテクチャにより、30B パラメータでも活性 3B で高速推論
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
│  Ollama（ホスト直接実行）                               │
│  ├── Metal GPU アクセラレーション有効                    │
│  ├── Qwen3-30B-A3B（MoE, Q4_K_M）← メイン推論         │
│  ├── Qwen3-4B（Q8_0）← 軽量判断・ルーティング           │
│  └── nomic-embed-text ← 埋め込み生成                   │
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
| Ollama（ホスト） | ~20GB | Qwen3-30B-A3B Q4_K_M: ~18GB + overhead |
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

[本プロジェクト]
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

#### Perception Skills — 知覚・情報収集

| Skill 名 | 説明 | Phase | 常時稼働 |
|-----------|------|-------|---------|
| `browse_x_timeline` | X タイムラインのスクロール・投稿収集 | 1 | Phase 0 判定次第 |
| `browse_x_search` | X 検索（キーワード / ハッシュタグ）— **1 日 5 回上限** | 1 | Phase 0 判定次第 |
| `browse_web_page` | 任意の URL を開いてコンテンツ抽出 | 1 | **常時** |
| `browse_news` | ニュースサイト巡回・記事収集 | 1 | **常時** |
| `browse_hacker_news` | HN Firebase API 経由でトップ記事取得 | 1 | **常時** |
| `browse_github_trending` | GitHub Trending 巡回 | 1 | **常時** |
| `fetch_rss` | RSS フィード取得・パース（ブラウザ不要） | 1 | **常時** |
| `browse_tech_feed` | 技術ブログ巡回 | 2 | **常時** |
| `monitor_diff` | ページ差分監視（前回との比較） | 2 | **常時** |

#### Action Skills — Web アクション

| Skill 名 | 説明 | Phase |
|-----------|------|-------|
| `click_element` | 指定要素のクリック | 1 |
| `fill_form` | フォーム入力 | 1 |
| `navigate_to` | URL 遷移 | 1 |
| `post_x` | X に投稿（キャラクターとして発信） | 3 |
| `reply_x` | X の投稿にリプライ | 3 |
| `send_discord` | Discord チャンネルにメッセージ送信 | 2 |

#### Memory Skills — 記憶・学習

| Skill 名 | 説明 | Phase |
|-----------|------|-------|
| `store_episodic` | 行動ログを Episodic Memory に保存 | 1 |
| `store_semantic` | 抽出した知識を Semantic Memory に保存 | 1 |
| `store_procedural` | 成功パターンを Procedural Memory に保存 | 2 |
| `recall_related` | 関連記憶を検索・取得 | 1 |
| `compress_memory` | 古い記憶の圧縮・統合 | 2 |
| `forget_low_value` | 低重要度記憶の削除 | 2 |

#### Reasoning Skills — 推論・判断

| Skill 名 | 説明 | Phase |
|-----------|------|-------|
| `select_skill` | 状況に応じて次に実行する Skill を選択（Agent の中核） | 1 |
| `plan_task` | タスクを具体的なアクション列に分解 | 1 |
| `build_llm_context` | LLM 呼び出し前に Working Memory を組み立てる | 1 |
| `llm_call` | Ollama への統一リクエスト送信（モデル自動選択） | 1 |
| `parse_llm_output` | LLM 出力の JSON パース（3 段階フォールバック） | 1 |
| `resolve_prompt` | YAML テンプレートに変数を注入してプロンプト生成 | 1 |
| `reflect` | 行動結果の振り返り・評価 | 2 |
| `evaluate_importance` | 情報の重要度スコアリング | 2 |
| `generate_goal` | 自律的な目標生成 | 3 |

#### Character Skills — キャラクター・対話

| Skill 名 | 説明 | Phase |
|-----------|------|-------|
| `build_persona_context` | 6 層キャラクター状態からプロンプト用コンテキスト生成 | 2 |
| `generate_response` | キャラクター性のある応答生成 | 2 |
| `update_emotion` | L3 感情状態 + L4 認知状態の更新 | 3 |
| `update_character_state` | L2〜L5 の緩慢変化レイヤーの定期更新 | 3 |
| `maintain_presence` | X / Discord での存在感維持行動 | 3 |

#### Browser Meta Skills — ブラウザ制御

| Skill 名 | 説明 | Phase |
|-----------|------|-------|
| `human_behavior` | ブラウザ操作に人間的な揺らぎを付与するメタ Skill | 1 |
| `verify_x_session` | X のセッション有効性を確認する | 1 |

**Skill 総数: 38**（Perception 9 / Action 7 / Memory 6 / Reasoning 9 / Character 5 / Browser 2）
詳細定義は `design-02-skill-definition-yaml-templates.md` + `design-03-llm-prompt-context-management.md` を参照。

### 4.4 LLM 駆動の Skill 選択フロー

Agent は固定パイプラインではなく、LLM が状況を分析して Skill を動的に選択する。

```
[Scheduler: 次のタイムスロット到達]
     │
     ▼
[select_skill Skill 呼び出し]
  LLM への入力（YAML 形式）:
    current_state:
      time: "2026-03-31T14:00:00+09:00"
      last_action: "browse_x_timeline"
      last_action_result: "5 posts collected about AI agents"
      pending_goals:
        - "AI Agent の最新動向を追跡する"
        - "Discord でユーザーの質問に答える"
      memory_summary: "直近3時間でAI関連15件、Solana関連3件を収集"
      presence:
        x: "30分前に最終閲覧"
        discord: "10分前にメッセージ応答"
    available_skills:
      - name: browse_x_timeline
        description: "Xタイムラインの閲覧・投稿収集"
      - name: browse_news
        description: "ニュースサイト巡回"
      - name: send_discord
        description: "Discordメッセージ送信"
      # ... 全 Skill の name + description
     │
     ▼
  LLM の出力（JSON 形式）:
    {
      "selected_skill": "browse_news",
      "reason": "AI関連はXで十分収集済み。ニュースサイトで補完情報を取得する",
      "parameters": {
        "sites": ["techcrunch", "theverge"],
        "topic": "AI agents autonomous"
      }
    }
     │
     ▼
[Skill Engine: browse_news を実行]
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
│  [episodic]  行動ログ・体験記録          │
│   payload: {timestamp, action, result, │
│             context, importance_score}  │
│   TTL: 30日（importance > 0.8 は永続）  │
│                                        │
│  [semantic]  抽出された知識・事実         │
│   payload: {topic, content, source,    │
│             confidence, extracted_at}   │
│   定期的に compress_memory で統合        │
│                                        │
│  [procedural] 成功パターン・手順         │
│   payload: {task_type, skill_sequence, │
│             success_rate, avg_duration} │
│   成功率が高いほど select_skill で優先   │
│                                        │
│  [character]  キャラクター関連記憶        │
│   payload: {interaction, user_id,      │
│             relationship, preference}   │
└────────────────────────────────────────┘
```

### 5.2 記憶の Write-Manage-Read ループ

1. **Write**: 行動後に `reflect` Skill が結果を評価し、`importance_score` 付きで JSON として記憶に保存
2. **Manage**: `compress_memory` Skill が定期的にメモリを走査。類似記憶の統合、低重要度記憶の TTL 期限切れ削除を実施
3. **Read**: `recall_related` Skill がタスク実行前に関連記憶を検索し、Working Memory に注入

---

## 6. ファイル規約: INPUT = YAML / OUTPUT = JSON

### 6.1 YAML（入力・設定・定義）

| 用途 | パス | 例 |
|------|------|----|
| Skill 定義 | `config/skills/*.yaml` | browse_x.yaml, store_episodic.yaml |
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

ブラウザ操作に人間的な揺らぎを付与するメタ Skill。詳細は `design-01-x-browser-access-strategy.md` に記載。

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
    skill: browse_hacker_news
    frequency_min: 60
    stealth_required: false
    always_active: true

  - name: github_trending
    type: browser
    url: "https://github.com/trending"
    skill: browse_github_trending
    frequency_min: 360
    stealth_required: false
    always_active: true

  - name: rss_feeds
    type: rss
    skill: fetch_rss
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
    skill: browse_news_site
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
    skill: browse_x_timeline
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

### 8.1 マルチモデル構成（全て Qwen3 量子化）

| 用途 | モデル | パラメータ | 量子化 | VRAM | 想定速度 |
|------|--------|-----------|--------|------|----------|
| Skill 選択・推論（メイン） | Qwen3-30B-A3B | 30B（活性 3B） | Q4_K_M | ~18GB | 高速（MoE） |
| 複雑な文章生成・分析 | Qwen3-14B | 14B | Q4_K_M | ~8GB | 中程度 |
| 軽量判断・ルーティング | Qwen3-4B | 4B | Q8_0 | ~4GB | 非常に高速 |
| 埋め込み生成 | nomic-embed-text | 137M | FP16 | ~0.3GB | 非常に高速 |

### 8.2 モデル切替戦略

LLM 呼び出しを `llm_call` Skill として統一し、タスクの重さに応じてモデルを自動選択する。

```yaml
# config/llm_routing.yaml
routing_rules:
  - condition: "skill_selection"
    model: qwen3-30b-a3b
    reason: "Skill選択は推論品質が最重要"
  - condition: "simple_classification"
    model: qwen3-4b
    reason: "Yes/No判断は軽量モデルで十分"
  - condition: "text_generation"
    model: qwen3-14b
    reason: "文章生成は中型モデルでバランス"
  - condition: "embedding"
    model: nomic-embed-text
    reason: "埋め込みは専用モデル"
```

### 8.3 Ollama 最適化

- **KV キャッシュ**: `OLLAMA_NUM_CTX=8192` で必要十分なコンテキスト長に制限
- **モデルロード管理**: `OLLAMA_KEEP_ALIVE=10m` で使用後 10 分でアンロード、メモリ解放
- **同時推論防止**: agent-core 側で推論キューを実装し、Ollama への同時リクエストを 1 に制限

---

## 9. 自律行動ループ

### 9.1 メインループ

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
│   ├── skills/                      # Skill 定義
│   │   ├── browse_x_timeline.yaml
│   │   ├── browse_x_search.yaml
│   │   ├── browse_web_page.yaml
│   │   ├── click_element.yaml
│   │   ├── store_episodic.yaml
│   │   ├── recall_related.yaml
│   │   ├── select_skill.yaml
│   │   ├── reflect.yaml
│   │   ├── human_behavior.yaml
│   │   └── ...
│   ├── characters/                  # キャラクター定義
│   │   └── agent_character.yaml     # 6層心理フレームワーク
│   ├── schedules/                   # スケジュール定義
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
│   │   │   │   ├── browse_x.py
│   │   │   │   ├── browse_web.py
│   │   │   │   └── monitor_diff.py
│   │   │   ├── action/              # アクション系
│   │   │   │   ├── browser_action.py
│   │   │   │   ├── post_x.py
│   │   │   │   └── send_discord.py
│   │   │   ├── memory/              # 記憶系
│   │   │   │   ├── episodic.py
│   │   │   │   ├── semantic.py
│   │   │   │   ├── procedural.py
│   │   │   │   └── memory_manager.py
│   │   │   ├── reasoning/           # 推論系
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
│   │       └── ollama_client.py     # Ollama HTTP クライアント
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
    ├── design-01-x-browser-access-strategy.md  # X アクセス戦略 詳細設計
    ├── character-design.md
    ├── memory-policy.md
    └── stealth-strategy.md
```

---

## 13. 実装フェーズ

### Phase 0: 技術検証（1〜2 週間）

**目的**: ローカル LLM × Playwright Stealth の実用性を確認する。X アクセスの Go / No-Go を判定する。

- [ ] ホストで Ollama + Qwen3-30B-A3B を起動し推論速度を計測
- [ ] Docker 内 Playwright Stealth で bot.sannysoft.com / browserscan.net を通過できるか検証
- [ ] Browser Use + Ollama（`host.docker.internal`）で単純 Web タスクを実行
- [ ] **X 検証**: タイムライン閲覧 10 回試行（8/10 合格）、検索 5 回試行（3/5 合格）
- [ ] **X 72 時間テスト**: 低頻度（1 日 3 セッション）で 3 日間稼働しアカウント停止なし
- [ ] **代替ソース検証**: Hacker News API / GitHub Trending / RSS の取得パイプライン構築
- [ ] Qdrant に検索結果を JSON で保存・検索する基本パイプラインを構築
- [ ] SkillSpec YAML → dataclass ロードの基盤実装
- [ ] **Go / No-Go 判定**

**判定基準**:

| 結果 | 判定 | 次のアクション |
|------|------|--------------|
| X 検証 + LLM 速度 全合格 | **Go** | X を含む全ソースで Phase 1 |
| X 不安定だが LLM/代替ソースは OK | **条件付き** | X は低頻度運用 + 代替ソースを主軸に Phase 1 |
| X アカウント停止 | **X 断念** | 代替ソースのみで Phase 1。Agent は X なしでも成立する |
| LLM 推論が遅すぎる | **モデル見直し** | より小さいモデルを検証、またはタスク分割の設計変更 |

### Phase 1: 情報収集 Agent（2〜3 週間）

**目的**: Web 閲覧・情報収集の自律ループ（Skill ベース）を完成させる

- [ ] docker-compose.yml 完成（agent-core, browser, qdrant）
- [ ] core/skill_engine.py: YAML → SkillSpec ロード + 実行エンジン
- [ ] core/skill_trace.py: SkillTrace / PipelineTrace → JSONL 出力
- [ ] Perception Skills 実装（常時稼働ソース）: browse_news, browse_hacker_news, browse_github_trending, fetch_rss, browse_web_page
- [ ] Perception Skills 実装（X — Phase 0 結果次第）: browse_x_timeline, browse_x_search + HumanBehavior Skill
- [ ] information_sources.yaml に基づくソースマネージャ（フォールバック自動切替含む）
- [ ] Memory Skills 実装: store_episodic, store_semantic, recall_related
- [ ] Reasoning Skills 実装: select_skill（LLM 駆動）, plan_task
- [ ] Context Management Skills 実装: build_llm_context, llm_call, parse_llm_output, resolve_prompt
- [ ] HumanBehavior Skill（操作の人間化）
- [ ] Scheduler + Presence Monitor 基盤

**成果物**: 複数の情報源（X / ニュース / HN / GitHub / RSS）を自律巡回し、Skill を選択しながら情報を蓄積する Agent。X がなくても動く。

### Phase 2: 記憶強化 + キャラクター（3〜4 週間）

**目的**: 3 層メモリとキャラクター性の実装

- [ ] Memory Skills 拡充: store_semantic, store_procedural, compress_memory, forget_low_value
- [ ] Reasoning Skills: reflect, evaluate_importance
- [ ] Character Skills: build_persona_context, generate_response
- [ ] キャラクター YAML に具体的な内容を設定（6 層フレームワークは設計済み: design-04）
- [ ] Action Skills: send_discord（Discord 連携）
- [ ] 安全機構の完全実装（サーキットブレーカー、リソースガード）
- [ ] Dashboard UI 基盤（行動ログ、記憶の可視化）

**成果物**: 経験から学習し、キャラクター性を持って Discord で応答する Agent

### Phase 3: 完全自律 + デュアルプレゼンス（3〜4 週間）

**目的**: 24 時間自律稼働と X / Discord 常時存在

- [ ] Reasoning Skills: generate_goal（自律目標生成）
- [ ] Action Skills: post_x, reply_x（X での発信）
- [ ] Character Skills: update_emotion, maintain_presence
- [ ] Presence Monitor 完全実装（X / Discord デュアル）
- [ ] アウトプット生成: Daily Digest, Topic Report, Trend Alert
- [ ] 長時間稼働テスト（24h → 72h → 1 週間）
- [ ] Dashboard 完成版

**成果物**: 24 時間自律稼働し、X と Discord に常駐するキャラクター Agent

### Phase 4: 発展・最適化（継続的）

- [ ] Zethi / Prako との連携（マルチエージェント）
- [ ] GraphRAG 導入（知識グラフ）
- [ ] Procedural Memory による Skill 実行自動最適化
- [ ] 新モデル検証・移行
- [ ] VOICEVOX 連携（音声出力対応）

---

## 14. 既存資産の活用

| 既存資産 | 活用先 |
|----------|--------|
| Zethi/Prako Discord Agent | エージェントループ設計、Discord bot 基盤 |
| Talkov-Chan Skill Architecture | SkillSpec / SkillTrace 設計パターン |
| Qdrant + nomic-embed-text | 記憶システム（階層チャンキング経験） |
| 6 層心理フレームワーク | キャラクタープロファイル設計 |
| ConoHa VPS + Docker 運用 | Docker Compose 構成、永続化設計 |
| AITuber（Ollama + VOICEVOX） | ローカル LLM 運用ノウハウ |

---

## 15. 次のアクション（設計フェーズ）

環境構築は設計が固まってから。まずは以下の設計成果物を順に作成する。

| # | 設計ブロック | 成果物 | ステータス |
|---|-------------|--------|-----------|
| 1 | X ブラウザアクセス戦略 | `design-01-x-browser-access-strategy.md` | ✅ 完了 |
| 2 | Skill 定義 + YAML テンプレート | `design-02-skill-definition-yaml-templates.md` | ✅ 完了 |
| 3 | LLM プロンプト / コンテキスト管理設計 | `design-03-llm-prompt-context-management.md` | ✅ 完了 |
| 4 | キャラクターフレームワーク（6 層モデル） | `design-04-character-framework.md` | ✅ 完了 |



---
---

# Part 2: X ブラウザアクセス戦略 詳細設計


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

### 5.1 読取系 Skill（Phase 1 対象）

#### browse_x_timeline

```yaml
# config/skills/browse_x_timeline.yaml

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
---

# Part 3: Skill 定義 + YAML テンプレート 詳細設計


## 1. SkillSpec 共通スキーマ

全 Skill は以下の共通スキーマに従って YAML で定義する。
起動時に Python dataclass `SkillSpec` にロードされる。

### 1.1 スキーマ定義

```yaml
# ===== SkillSpec 共通スキーマ =====
# 全 Skill の YAML はこの構造に従う

# --- 識別 ---
name: string                    # Skill の一意名（snake_case）
category: enum                  # perception | action | memory | reasoning | character | browser
version: string                 # セマンティックバージョン（"1.0.0"）

# --- 説明（LLM が Skill を選択する際に参照する）---
description: string             # 1行の説明文（日本語）
when_to_use: string             # どういう状況で使うべきかの指針（LLM 向け）
when_not_to_use: string         # 使うべきでない状況（LLM 向け）

# --- 入出力定義 ---
input:
  required:                     # 必須パラメータ
    param_name:
      type: string              # str | int | float | bool | list[str] | dict
      description: string
  optional:                     # 任意パラメータ（デフォルト値あり）
    param_name:
      type: string
      default: any
      description: string

output:
  fields:
    field_name:
      type: string
      description: string

# --- 実行制御 ---
execution:
  timeout_sec: int              # タイムアウト（秒）
  max_retries: int              # 最大リトライ回数
  retry_delay_sec: int          # リトライ間隔（秒）
  requires: list[string]        # 依存リソース（browser | stealth | qdrant | ollama）
  model: string | null          # 使用する LLM モデル名（null = LLM 不要）
  async: bool                   # 非同期実行可能か

# --- レート制限 ---
rate_limit:
  max_per_hour: int | null      # 1時間あたりの最大実行回数
  max_per_day: int | null       # 1日あたりの最大実行回数
  min_interval_sec: int | null  # 最小実行間隔（秒）
  cool_down_on_failure_sec: int # 失敗時のクールダウン（秒）

# --- リスク・安全 ---
risk_level: enum                # none | low | medium | high | critical
on_failure: enum                # retry | skip | pause_and_notify | emergency_stop
priority: int                   # 0-100（高いほど select_skill で優先されやすい）

# --- メタデータ ---
phase: int                      # 実装フェーズ（0, 1, 2, 3）
tags: list[string]              # 検索用タグ
depends_on: list[string]        # 前提 Skill（実行前に完了が必要）
```

### 1.2 対応する Python dataclass

```python
# core/skill_spec.py

from dataclasses import dataclass, field
from typing import Callable, Any

@dataclass
class ParamSpec:
    type: str
    description: str
    default: Any = None
    required: bool = True

@dataclass
class SkillSpec:
    name: str
    category: str
    version: str
    description: str
    when_to_use: str
    when_not_to_use: str

    input_required: dict[str, ParamSpec]
    input_optional: dict[str, ParamSpec]
    output_fields: dict[str, ParamSpec]

    timeout_sec: int
    max_retries: int
    retry_delay_sec: int = 1
    requires: list[str] = field(default_factory=list)
    model: str | None = None
    is_async: bool = False

    max_per_hour: int | None = None
    max_per_day: int | None = None
    min_interval_sec: int | None = None
    cool_down_on_failure_sec: int = 60

    risk_level: str = "none"
    on_failure: str = "retry"
    priority: int = 50
    phase: int = 1
    tags: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)

    # 起動時にバインドされる実行関数
    func: Callable | None = None
```

---

## 2. Skill カタログ全一覧

全 33 Skill を一覧する。各 Skill の詳細 YAML は Section 3 以降で定義。

### 2.1 サマリーテーブル

| # | Skill 名 | カテゴリ | Phase | requires | model | risk | 常時稼働 |
|---|----------|---------|-------|----------|-------|------|---------|
| **Perception — 情報収集** | | | | | | | |
| 1 | `browse_x_timeline` | perception | 1 | browser, stealth | qwen3-4b | high | Phase 0 判定 |
| 2 | `browse_x_search` | perception | 1 | browser, stealth | qwen3-4b | critical | Phase 0 判定 |
| 3 | `browse_x_profile` | perception | 2 | browser, stealth | qwen3-4b | medium | Phase 0 判定 |
| 4 | `browse_web_page` | perception | 1 | browser | qwen3-4b | low | **常時** |
| 5 | `browse_news` | perception | 1 | browser | qwen3-4b | low | **常時** |
| 6 | `browse_hacker_news` | perception | 1 | — | qwen3-4b | none | **常時** |
| 7 | `browse_github_trending` | perception | 1 | browser | qwen3-4b | none | **常時** |
| 8 | `fetch_rss` | perception | 1 | — | — | none | **常時** |
| 9 | `monitor_diff` | perception | 2 | qdrant | qwen3-4b | none | **常時** |
| **Action — Web操作** | | | | | | | |
| 10 | `click_element` | action | 1 | browser | — | low | — |
| 11 | `fill_form` | action | 1 | browser | — | medium | — |
| 12 | `navigate_to` | action | 1 | browser | — | low | — |
| 13 | `scroll_page` | action | 1 | browser, stealth | — | low | — |
| 14 | `post_x` | action | 3 | browser, stealth | qwen3-14b | critical | — |
| 15 | `reply_x` | action | 3 | browser, stealth | qwen3-14b | critical | — |
| 16 | `send_discord` | action | 2 | — | qwen3-14b | low | — |
| **Memory — 記憶** | | | | | | | |
| 17 | `store_episodic` | memory | 1 | qdrant | — | none | — |
| 18 | `store_semantic` | memory | 1 | qdrant | qwen3-4b | none | — |
| 19 | `store_procedural` | memory | 2 | qdrant | qwen3-4b | none | — |
| 20 | `recall_related` | memory | 1 | qdrant | — | none | — |
| 21 | `compress_memory` | memory | 2 | qdrant | qwen3-14b | none | — |
| 22 | `forget_low_value` | memory | 2 | qdrant | — | none | — |
| **Reasoning — 推論** | | | | | | | |
| 23 | `select_skill` | reasoning | 1 | ollama | **qwen3-30b-a3b** | none | — |
| 24 | `plan_task` | reasoning | 1 | ollama | qwen3-30b-a3b | none | — |
| 25 | `reflect` | reasoning | 2 | ollama, qdrant | qwen3-14b | none | — |
| 26 | `generate_goal` | reasoning | 3 | ollama, qdrant | qwen3-30b-a3b | none | — |
| 27 | `evaluate_importance` | reasoning | 2 | ollama | qwen3-4b | none | — |
| **Character — キャラクター** | | | | | | | |
| 28 | `build_persona_context` | character | 2 | — | — | none | — |
| 29 | `generate_response` | character | 2 | ollama | qwen3-14b | none | — |
| 30 | `update_emotion` | character | 3 | — | qwen3-4b | none | — |
| 31 | `maintain_presence` | character | 3 | — | qwen3-4b | none | — |
| **Browser — ブラウザメタ** | | | | | | | |
| 32 | `human_behavior` | browser | 1 | browser | — | none | — |
| 33 | `verify_x_session` | browser | 1 | browser, stealth | — | none | — |

---

## 3. Phase 1 Skill 詳細 YAML（16 Skill）

Phase 1 で実装する全 Skill の詳細定義。

### 3.1 Perception Skills

#### browse_x_timeline

```yaml
name: browse_x_timeline
category: perception
version: "1.0.0"
description: "Xのホームタイムラインをスクロールし、投稿を収集する"
when_to_use: "Xのリアルタイム情報を収集したい時。トレンドや最新の話題を把握したい時"
when_not_to_use: "X操作の日次上限に達している時。直近30分以内にXにアクセス済みの時"

input:
  required:
    topic_filter:
      type: str
      description: "収集対象のトピック。LLMが関連性判定に使用"
  optional:
    max_posts:
      type: int
      default: 20
      description: "収集する最大投稿数"
    scroll_depth:
      type: int
      default: 15
      description: "スクロール回数"

output:
  fields:
    posts:
      type: "list[dict]"
      description: "収集した投稿リスト {id, author, content, timestamp, engagement, is_relevant}"
    collected_at:
      type: str
      description: "収集日時（ISO 8601）"
    scroll_count:
      type: int
      description: "実際のスクロール回数"
    session_duration_sec:
      type: int
      description: "セッション所要時間（秒）"

execution:
  timeout_sec: 300
  max_retries: 1
  retry_delay_sec: 60
  requires: [browser, stealth]
  model: qwen3-4b
  async: false

rate_limit:
  max_per_hour: 2
  max_per_day: 6
  min_interval_sec: 1800
  cool_down_on_failure_sec: 3600

risk_level: high
on_failure: pause_and_notify
priority: 60
phase: 1
tags: [x, timeline, information_gathering]
depends_on: [verify_x_session, human_behavior]
```

#### browse_x_search

```yaml
name: browse_x_search
category: perception
version: "1.0.0"
description: "Xの検索機能でキーワード検索し結果を収集する。1日5回上限"
when_to_use: "特定のキーワードやハッシュタグについてXでの反応を調べたい時。タイムラインでは見つからない情報が必要な時"
when_not_to_use: "検索の日次上限(5回)に達している時。タイムライン閲覧で十分な情報が得られる時"

input:
  required:
    query:
      type: str
      description: "検索クエリ"
  optional:
    search_type:
      type: str
      default: "latest"
      description: "'latest' | 'top' | 'people' | 'media'"
    max_results:
      type: int
      default: 10
      description: "最大取得件数"

output:
  fields:
    results:
      type: "list[dict]"
      description: "検索結果 {id, author, content, timestamp, engagement}"
    query_used:
      type: str
      description: "実際に使用した検索クエリ"

execution:
  timeout_sec: 180
  max_retries: 0
  requires: [browser, stealth]
  model: qwen3-4b
  async: false

rate_limit:
  max_per_hour: 1
  max_per_day: 5
  min_interval_sec: 3600
  cool_down_on_failure_sec: 21600

risk_level: critical
on_failure: pause_and_notify
priority: 40
phase: 1
tags: [x, search, information_gathering]
depends_on: [verify_x_session, human_behavior]
```

#### browse_web_page

```yaml
name: browse_web_page
category: perception
version: "1.0.0"
description: "任意のURLを開いてページ内容を抽出する。X以外の一般Webサイト用"
when_to_use: "特定のURLの内容を取得したい時。ニュース記事やブログの全文を読みたい時"
when_not_to_use: "Xのページにアクセスする時（browse_x系を使う）。RSS取得で十分な時"

input:
  required:
    url:
      type: str
      description: "アクセスするURL"
  optional:
    extract_mode:
      type: str
      default: "article"
      description: "'article'（本文抽出） | 'full'（全DOM） | 'links'（リンク一覧）"
    wait_for:
      type: str
      default: "networkidle"
      description: "ページ読み込み完了の判定条件"

output:
  fields:
    title:
      type: str
      description: "ページタイトル"
    content:
      type: str
      description: "抽出されたテキスト内容"
    links:
      type: "list[dict]"
      description: "ページ内のリンク一覧 {text, href}"
    metadata:
      type: dict
      description: "OGP等のメタ情報"

execution:
  timeout_sec: 60
  max_retries: 2
  retry_delay_sec: 5
  requires: [browser]
  model: null
  async: false

rate_limit:
  max_per_hour: 30
  max_per_day: 200
  min_interval_sec: 10
  cool_down_on_failure_sec: 30

risk_level: low
on_failure: retry
priority: 70
phase: 1
tags: [web, scraping, information_gathering]
depends_on: []
```

#### browse_news

```yaml
name: browse_news
category: perception
version: "1.0.0"
description: "ニュースサイトを巡回し、最新記事のタイトルとサマリーを収集する"
when_to_use: "最新のニュースやトレンドを把握したい時。定期巡回タスクとして"
when_not_to_use: "特定のURLの内容を読みたい時（browse_web_pageを使う）"

input:
  required:
    site:
      type: str
      description: "巡回するサイト識別子（config/information_sources.yamlのnameに対応）"
  optional:
    max_articles:
      type: int
      default: 10
      description: "収集する最大記事数"
    topic_filter:
      type: str
      default: ""
      description: "関心トピック（空文字なら全記事）"

output:
  fields:
    articles:
      type: "list[dict]"
      description: "記事リスト {title, url, summary, published_at, source}"
    site_name:
      type: str
      description: "巡回したサイト名"

execution:
  timeout_sec: 90
  max_retries: 2
  retry_delay_sec: 10
  requires: [browser]
  model: qwen3-4b
  async: false

rate_limit:
  max_per_hour: 4
  max_per_day: null
  min_interval_sec: 600
  cool_down_on_failure_sec: 120

risk_level: low
on_failure: retry
priority: 75
phase: 1
tags: [news, information_gathering, always_active]
depends_on: []
```

#### browse_hacker_news

```yaml
name: browse_hacker_news
category: perception
version: "1.0.0"
description: "Hacker NewsのFirebase APIからトップ記事を取得する。ブラウザ不要"
when_to_use: "技術コミュニティの話題やトレンドを把握したい時。定期巡回タスクとして"
when_not_to_use: "HN以外のソースで十分な情報がある時"

input:
  optional:
    story_type:
      type: str
      default: "top"
      description: "'top' | 'new' | 'best' | 'ask' | 'show'"
    max_stories:
      type: int
      default: 15
      description: "取得する最大記事数"

output:
  fields:
    stories:
      type: "list[dict]"
      description: "記事リスト {id, title, url, score, author, comment_count, time}"

execution:
  timeout_sec: 30
  max_retries: 3
  retry_delay_sec: 5
  requires: []
  model: null
  async: true

rate_limit:
  max_per_hour: 4
  max_per_day: null
  min_interval_sec: 600
  cool_down_on_failure_sec: 60

risk_level: none
on_failure: retry
priority: 80
phase: 1
tags: [hackernews, api, information_gathering, always_active]
depends_on: []
```

#### browse_github_trending

```yaml
name: browse_github_trending
category: perception
version: "1.0.0"
description: "GitHub Trendingページを巡回し、注目リポジトリを収集する"
when_to_use: "技術トレンドやOSSの動向を把握したい時"
when_not_to_use: "直近6時間以内に巡回済みの時"

input:
  optional:
    language:
      type: str
      default: ""
      description: "言語フィルタ（空文字なら全言語）"
    since:
      type: str
      default: "daily"
      description: "'daily' | 'weekly' | 'monthly'"

output:
  fields:
    repositories:
      type: "list[dict]"
      description: "リポジトリリスト {name, url, description, language, stars_today, total_stars}"

execution:
  timeout_sec: 60
  max_retries: 2
  retry_delay_sec: 10
  requires: [browser]
  model: null
  async: false

rate_limit:
  max_per_hour: 1
  max_per_day: 4
  min_interval_sec: 3600
  cool_down_on_failure_sec: 120

risk_level: none
on_failure: retry
priority: 65
phase: 1
tags: [github, trending, information_gathering, always_active]
depends_on: []
```

#### fetch_rss

```yaml
name: fetch_rss
category: perception
version: "1.0.0"
description: "RSSフィードを取得・パースする。ブラウザ不要。最も軽量な情報収集手段"
when_to_use: "定期的な情報更新の確認。新着記事の検知。低コストで広範囲の情報を集めたい時"
when_not_to_use: "全文が必要な時（RSSはサマリーのみの場合が多い）"

input:
  required:
    feed_url:
      type: str
      description: "RSSフィードのURL"
  optional:
    max_items:
      type: int
      default: 20
      description: "取得する最大アイテム数"
    since_hours:
      type: int
      default: 24
      description: "直近N時間の記事のみ取得"

output:
  fields:
    items:
      type: "list[dict]"
      description: "フィードアイテム {title, url, summary, published_at, author}"
    feed_title:
      type: str
      description: "フィード名"

execution:
  timeout_sec: 15
  max_retries: 3
  retry_delay_sec: 5
  requires: []
  model: null
  async: true

rate_limit:
  max_per_hour: 10
  max_per_day: null
  min_interval_sec: 300
  cool_down_on_failure_sec: 60

risk_level: none
on_failure: retry
priority: 85
phase: 1
tags: [rss, information_gathering, always_active, lightweight]
depends_on: []
```

### 3.2 Action Skills

#### click_element

```yaml
name: click_element
category: action
version: "1.0.0"
description: "指定されたセレクタまたはテキストの要素をクリックする"
when_to_use: "ブラウザ上の特定の要素をクリックする必要がある時"
when_not_to_use: "ページ遷移が目的の時（navigate_toを使う）"

input:
  required:
    target:
      type: str
      description: "CSSセレクタ、XPath、またはテキスト内容"
  optional:
    target_type:
      type: str
      default: "auto"
      description: "'css' | 'xpath' | 'text' | 'auto'（自動判定）"
    use_human_behavior:
      type: bool
      default: true
      description: "human_behavior Skillを適用するか"

output:
  fields:
    success:
      type: bool
      description: "クリック成功したか"
    element_found:
      type: bool
      description: "要素が見つかったか"

execution:
  timeout_sec: 15
  max_retries: 2
  retry_delay_sec: 2
  requires: [browser]
  model: null
  async: false

risk_level: low
on_failure: retry
priority: 50
phase: 1
tags: [browser, action, basic]
depends_on: []
```

#### navigate_to

```yaml
name: navigate_to
category: action
version: "1.0.0"
description: "指定されたURLに遷移する"
when_to_use: "新しいページに移動する必要がある時"
when_not_to_use: "現在のページ内の操作で十分な時"

input:
  required:
    url:
      type: str
      description: "遷移先のURL"
  optional:
    wait_for:
      type: str
      default: "domcontentloaded"
      description: "'load' | 'domcontentloaded' | 'networkidle'"
    use_human_behavior:
      type: bool
      default: false
      description: "遷移前に人間的な遅延を入れるか"

output:
  fields:
    success:
      type: bool
      description: "遷移成功したか"
    final_url:
      type: str
      description: "リダイレクト後の最終URL"
    status_code:
      type: int
      description: "HTTPステータスコード"

execution:
  timeout_sec: 30
  max_retries: 2
  retry_delay_sec: 5
  requires: [browser]
  model: null
  async: false

risk_level: low
on_failure: retry
priority: 50
phase: 1
tags: [browser, action, basic]
depends_on: []
```

#### scroll_page

```yaml
name: scroll_page
category: action
version: "1.0.0"
description: "ページをスクロールする。human_behaviorと連携して自然なスクロールを実現"
when_to_use: "ページ下部のコンテンツを読み込む必要がある時。無限スクロールのページで情報を収集する時"
when_not_to_use: "ページ内の特定要素にアクセスするだけの時（click_elementを使う）"

input:
  optional:
    direction:
      type: str
      default: "down"
      description: "'down' | 'up'"
    amount:
      type: int
      default: 3
      description: "スクロール回数"
    use_human_behavior:
      type: bool
      default: true
      description: "human_behaviorの揺らぎを適用するか"

output:
  fields:
    scrolled_count:
      type: int
      description: "実際にスクロールした回数"
    reached_bottom:
      type: bool
      description: "ページ末端に到達したか"

execution:
  timeout_sec: 60
  max_retries: 1
  requires: [browser]
  model: null
  async: false

risk_level: low
on_failure: skip
priority: 50
phase: 1
tags: [browser, action, basic]
depends_on: []
```

### 3.3 Memory Skills

#### store_episodic

```yaml
name: store_episodic
category: memory
version: "1.0.0"
description: "行動ログをEpisodic Memoryに保存する。全Skill実行後に自動呼び出し"
when_to_use: "Skill実行の結果を記録する時。自動的に呼び出されるため、明示的な選択は不要"
when_not_to_use: "知識の保存（store_semanticを使う）。成功パターンの保存（store_proceduralを使う）"

input:
  required:
    action:
      type: str
      description: "実行したアクション名（Skill名）"
    result_summary:
      type: str
      description: "結果の要約"
  optional:
    context:
      type: dict
      default: {}
      description: "実行時のコンテキスト情報"
    importance_score:
      type: float
      default: 0.5
      description: "重要度スコア（0.0〜1.0）。0.8以上は永続保存"

output:
  fields:
    stored:
      type: bool
      description: "保存成功したか"
    point_id:
      type: str
      description: "QdrantのポイントID"

execution:
  timeout_sec: 10
  max_retries: 2
  retry_delay_sec: 1
  requires: [qdrant]
  model: null
  async: true

risk_level: none
on_failure: skip
priority: 90
phase: 1
tags: [memory, episodic, logging]
depends_on: []
```

#### store_semantic

```yaml
name: store_semantic
category: memory
version: "1.0.0"
description: "抽出した知識・事実をSemantic Memoryに保存する。重複検知付き"
when_to_use: "新しい情報や知識を発見した時。ブラウジングで有用な事実を見つけた時"
when_not_to_use: "行動ログの保存（store_episodicを使う）"

input:
  required:
    content:
      type: str
      description: "保存する知識・事実の内容"
    topic:
      type: str
      description: "トピック分類"
    source:
      type: str
      description: "情報源URL or 識別子"
  optional:
    confidence:
      type: float
      default: 0.7
      description: "情報の信頼度（0.0〜1.0）"

output:
  fields:
    stored:
      type: bool
      description: "保存成功したか"
    is_duplicate:
      type: bool
      description: "既存知識と重複していたか"
    similar_existing:
      type: "list[str]"
      description: "類似する既存知識のID一覧"

execution:
  timeout_sec: 15
  max_retries: 2
  requires: [qdrant]
  model: qwen3-4b
  async: true

risk_level: none
on_failure: skip
priority: 85
phase: 1
tags: [memory, semantic, knowledge]
depends_on: []
```

#### recall_related

```yaml
name: recall_related
category: memory
version: "1.0.0"
description: "クエリに関連する記憶をQdrantから検索して取得する"
when_to_use: "タスク実行前に関連知識を確認したい時。質問に回答する前にコンテキストを補強したい時"
when_not_to_use: "記憶が不要な単純操作の時"

input:
  required:
    query:
      type: str
      description: "検索クエリ"
  optional:
    collections:
      type: "list[str]"
      default: ["episodic", "semantic", "procedural"]
      description: "検索対象のコレクション"
    top_k:
      type: int
      default: 5
      description: "取得する最大件数"
    min_score:
      type: float
      default: 0.6
      description: "最低類似度スコア"

output:
  fields:
    memories:
      type: "list[dict]"
      description: "検索結果 {collection, content, score, metadata}"
    total_found:
      type: int
      description: "ヒット件数"

execution:
  timeout_sec: 10
  max_retries: 2
  requires: [qdrant]
  model: null
  async: false

risk_level: none
on_failure: skip
priority: 90
phase: 1
tags: [memory, recall, search]
depends_on: []
```

### 3.4 Reasoning Skills

#### select_skill

```yaml
name: select_skill
category: reasoning
version: "1.0.0"
description: "現在の状況を分析し、次に実行すべきSkillを選択する。Agentの自律行動の中核"
when_to_use: "自律ループの各イテレーションで自動的に呼び出される"
when_not_to_use: "このSkill自体を明示的に選択することはない（メタSkill）"

input:
  required:
    current_state:
      type: dict
      description: "現在の状態（時刻, 直前のアクション, 保留目標, 記憶サマリー, プレゼンス状態）"
    available_skills:
      type: "list[dict]"
      description: "選択可能なSkill一覧 {name, description, when_to_use, risk_level, rate_limit_remaining}"

output:
  fields:
    selected_skill:
      type: str
      description: "選択されたSkill名"
    reason:
      type: str
      description: "選択理由（日本語）"
    parameters:
      type: dict
      description: "Skillに渡すパラメータ"
    confidence:
      type: float
      description: "選択の確信度（0.0〜1.0）"

execution:
  timeout_sec: 30
  max_retries: 2
  retry_delay_sec: 3
  requires: [ollama]
  model: qwen3-30b-a3b
  async: false

risk_level: none
on_failure: retry
priority: 100
phase: 1
tags: [reasoning, core, autonomous]
depends_on: []
```

#### plan_task

```yaml
name: plan_task
category: reasoning
version: "1.0.0"
description: "高レベルの目標を具体的なSkill実行シーケンスに分解する"
when_to_use: "複数のSkillを連携させる必要がある複雑なタスクの時"
when_not_to_use: "単一のSkillで完結するシンプルなタスクの時"

input:
  required:
    goal:
      type: str
      description: "達成すべき目標"
  optional:
    constraints:
      type: "list[str]"
      default: []
      description: "制約条件"
    max_steps:
      type: int
      default: 10
      description: "最大ステップ数"

output:
  fields:
    plan:
      type: "list[dict]"
      description: "実行計画 [{step, skill, parameters, expected_output}]"
    estimated_duration_sec:
      type: int
      description: "推定所要時間（秒）"

execution:
  timeout_sec: 30
  max_retries: 1
  requires: [ollama]
  model: qwen3-30b-a3b
  async: false

risk_level: none
on_failure: retry
priority: 95
phase: 1
tags: [reasoning, planning, autonomous]
depends_on: [recall_related]
```

### 3.5 Browser Meta Skills

#### human_behavior

```yaml
name: human_behavior
category: browser
version: "1.0.0"
description: "ブラウザ操作に人間的な揺らぎを付与するメタSkill。他のSkillから暗黙的に呼び出される"
when_to_use: "Stealth が必要なブラウザ操作の前に自動適用される"
when_not_to_use: "API呼び出しやブラウザ不要の操作の時"

input:
  optional:
    intensity:
      type: str
      default: "normal"
      description: "'minimal'（最小限の揺らぎ） | 'normal' | 'paranoid'（最大限の人間模倣）"

output:
  fields:
    applied:
      type: bool
      description: "行動パターンが適用されたか"

execution:
  timeout_sec: 5
  max_retries: 0
  requires: [browser]
  model: null
  async: false

risk_level: none
on_failure: skip
priority: 100
phase: 1
tags: [browser, stealth, meta]
depends_on: []

# 行動パラメータは config/skills/human_behavior.yaml の parameters セクションで定義
# （design-01-x-browser-access-strategy.md Section 4 参照）
```

#### verify_x_session

```yaml
name: verify_x_session
category: browser
version: "1.0.0"
description: "Xのセッションが有効か確認する。X操作の前に自動呼び出し"
when_to_use: "X関連のSkill実行前に自動チェック"
when_not_to_use: "X以外のサイトにアクセスする時"

input: {}

output:
  fields:
    session_valid:
      type: bool
      description: "セッションが有効か"
    issue_type:
      type: "str | null"
      description: "'captcha' | 'login_required' | 'suspended' | 'rate_limited' | null"

execution:
  timeout_sec: 15
  max_retries: 0
  requires: [browser, stealth]
  model: null
  async: false

risk_level: none
on_failure: pause_and_notify
priority: 100
phase: 1
tags: [browser, stealth, x, session]
depends_on: []
```

---

## 4. Phase 2 Skill 概要定義（11 Skill）

Phase 2 の Skill は概要レベルで定義。Phase 1 完了後に詳細化する。

| Skill 名 | 概要 | model | 主な input | 主な output |
|-----------|------|-------|-----------|------------|
| `browse_x_profile` | 特定ユーザーのプロフィール・投稿を収集 | qwen3-4b | username | profile, posts |
| `browse_tech_feed` | 技術ブログ群の巡回 | qwen3-4b | site_list | articles |
| `monitor_diff` | ページの前回スナップショットとの差分検知 | qwen3-4b | url | diff_summary, changed |
| `fill_form` | フォーム入力（検索ボックス等） | — | selectors, values | success |
| `store_procedural` | 成功した Skill 実行シーケンスをパターンとして保存 | qwen3-4b | skill_sequence, success_rate | stored |
| `compress_memory` | 古い記憶の要約・統合 | qwen3-14b | collection, older_than_days | compressed_count |
| `forget_low_value` | importance_score が低い記憶の削除 | — | threshold, collection | deleted_count |
| `reflect` | 直近の行動を振り返り、改善点を抽出 | qwen3-14b | recent_actions | insights, adjustments |
| `evaluate_importance` | 情報の重要度をスコアリング | qwen3-4b | content, context | importance_score |
| `send_discord` | Discord チャンネルにメッセージ送信 | qwen3-14b | channel_id, message | sent |
| `build_persona_context` | キャラクタープロファイルからプロンプト用コンテキストを構築 | — | character_yaml | persona_context |
| `generate_response` | キャラクター性のある応答を生成 | qwen3-14b | query, persona_context, memories | response |

---

## 5. Phase 3 Skill 概要定義（6 Skill）

| Skill 名 | 概要 | model | 備考 |
|-----------|------|-------|------|
| `post_x` | X に投稿する | qwen3-14b | Bot ラベル付きアカウント推奨。Phase 0 の X 判定結果に依存 |
| `reply_x` | X の投稿にリプライする | qwen3-14b | 同上 |
| `generate_goal` | 自律的に新しい目標を生成する | qwen3-30b-a3b | Procedural Memory を参照して効果的な目標を立てる |
| `update_emotion` | キャラクターの感情状態を更新する | qwen3-4b | 行動結果に基づいて遷移 |
| `maintain_presence` | X/Discord での存在感を維持する行動を生成 | qwen3-4b | presence.yaml に基づく |

---

## 6. Skill 間の依存関係

### 6.1 暗黙的依存（自動チェーン）

以下の依存は Skill Engine が自動的に処理する。

```
X関連Skill → [verify_x_session] → [human_behavior] → 本体実行
全Skill実行後 → [store_episodic]（自動記録）
```

### 6.2 推奨チェーン（select_skill が学習する）

```
情報収集タスク:
  select_skill → recall_related → browse_* → store_semantic → reflect

質問応答タスク:
  recall_related → build_persona_context → generate_response → send_discord

定期巡回タスク:
  select_skill → [browse_hacker_news | fetch_rss | browse_news] → store_semantic

複雑な調査:
  plan_task → [browse_web_page × N] → store_semantic → generate_response
```

### 6.3 Skill 実行の禁止ルール

| ルール | 内容 |
|--------|------|
| 同時実行禁止 | LLM を使う Skill は同時に 1 つまで（Ollama 同時推論防止） |
| X 操作の排他 | X 関連 Skill は同時に 1 つまで（同一ブラウザコンテキスト） |
| 記憶書き込みの順序 | store_episodic → store_semantic の順序を保証 |
| cooldown 中の Skill はスキップ | rate_limit 超過の Skill は available_skills から除外 |

---

## 7. YAML ファイル配置と命名規則

```
config/skills/
├── perception/
│   ├── browse_x_timeline.yaml
│   ├── browse_x_search.yaml
│   ├── browse_x_profile.yaml
│   ├── browse_web_page.yaml
│   ├── browse_news.yaml
│   ├── browse_hacker_news.yaml
│   ├── browse_github_trending.yaml
│   ├── fetch_rss.yaml
│   ├── browse_tech_feed.yaml
│   └── monitor_diff.yaml
├── action/
│   ├── click_element.yaml
│   ├── fill_form.yaml
│   ├── navigate_to.yaml
│   ├── scroll_page.yaml
│   ├── post_x.yaml
│   ├── reply_x.yaml
│   └── send_discord.yaml
├── memory/
│   ├── store_episodic.yaml
│   ├── store_semantic.yaml
│   ├── store_procedural.yaml
│   ├── recall_related.yaml
│   ├── compress_memory.yaml
│   └── forget_low_value.yaml
├── reasoning/
│   ├── select_skill.yaml
│   ├── plan_task.yaml
│   ├── reflect.yaml
│   ├── generate_goal.yaml
│   ├── evaluate_importance.yaml
│   ├── build_llm_context.yaml     # design-03 で追加
│   ├── llm_call.yaml              # design-03 で追加
│   ├── parse_llm_output.yaml      # design-03 で追加
│   └── resolve_prompt.yaml        # design-03 で追加
├── character/
│   ├── build_persona_context.yaml
│   ├── generate_response.yaml
│   ├── update_emotion.yaml
│   ├── update_character_state.yaml # design-04 で追加
│   └── maintain_presence.yaml
└── browser/
    ├── human_behavior.yaml
    └── verify_x_session.yaml
```

命名規則:
- ファイル名 = Skill の `name` フィールドと一致（snake_case）
- カテゴリごとにサブディレクトリで分類
- 1ファイル = 1 Skill（例外なし）

---

## 8. Skill 総数

| 追加元 | 追加数 | 累計 |
|--------|-------|------|
| 本ドキュメント（design-02） | 33 | 33 |
| design-03（コンテキスト管理） | +4（build_llm_context, llm_call, parse_llm_output, resolve_prompt） | 37 |
| design-04（キャラクター状態更新） | +1（update_character_state） | **38** |



---
---

# Part 4: LLM プロンプト / コンテキスト管理 詳細設計


## 1. 設計思想

### 1.1 基本方針

LLM へ渡すプロンプトの組み立て・テンプレート管理・コンテキスト制御を
**全て Skill + YAML で管理可能にする**。ハードコードされたプロンプトは存在しない。

```
プロンプト生成の流れ:

config/prompts/*.yaml（テンプレート定義）
        ↓
build_llm_context Skill（コンテキスト組立）
        ↓
Working Memory（構造化された LLM 入力）
        ↓
llm_call Skill（Ollama へ送信）
        ↓
JSON 出力（構造化レスポンス）
```

### 1.2 Skill 化する対象

| 対象 | Skill 名 | 役割 |
|------|----------|------|
| コンテキスト組立 | `build_llm_context` | 各 Skill が LLM を呼ぶ前のコンテキスト構築 |
| LLM 呼び出し | `llm_call` | Ollama への統一的なリクエスト送信 |
| 出力パース | `parse_llm_output` | LLM 出力の JSON パース + バリデーション |
| テンプレート解決 | `resolve_prompt` | YAML テンプレートに変数を注入して最終プロンプトを生成 |

---

## 2. Working Memory 構造

### 2.1 概要

Working Memory は LLM に渡す「今この瞬間のコンテキスト」を構造化したもの。
揮発性で、1 回の LLM 呼び出しごとに組み立てられる。

```yaml
# Working Memory の構造（内部表現）
# build_llm_context Skill がこれを組み立てる

working_memory:
  # --- 現在の状態 ---
  current_state:
    timestamp: "2026-03-31T19:30:00+09:00"
    agent_name: "agent_character_name"
    active_goal: "AI Agent の最新動向を追跡する"
    last_action:
      skill: "browse_hacker_news"
      result: "15 stories collected, 3 relevant to AI agents"
      duration_ms: 2400
    presence:
      x:
        last_access: "2026-03-31T18:00:00+09:00"
        status: "active"
      discord:
        last_access: "2026-03-31T19:25:00+09:00"
        status: "active"

  # --- 記憶から取得した関連情報 ---
  recalled_memories:
    episodic:
      - "3時間前にTechCrunchでAI Agent記事を収集（5件）"
      - "昨日Xで自律エージェントのスレッドを発見"
    semantic:
      - "Browser Use は GitHub 50,000+ stars の OSS ブラウザ自動化ライブラリ"
      - "2026年2月、X は bot 検出を強化。自動検索は検出対象"
    procedural:
      - "ニュース収集 → 要約 → Discord共有 の成功率: 92%"

  # --- 利用可能な Skill 一覧（rate_limit 内のもののみ）---
  available_skills:
    - name: browse_x_timeline
      description: "Xのタイムラインを閲覧し投稿を収集する"
      when_to_use: "Xのリアルタイム情報を収集したい時"
      risk_level: high
      remaining_today: 4
    - name: browse_news
      description: "ニュースサイトを巡回し最新記事を収集する"
      when_to_use: "最新ニュースやトレンドを把握したい時"
      risk_level: low
      remaining_today: null
    # ... 全 available skills

  # --- キャラクターコンテキスト（build_persona_context から）---
  persona:
    personality_summary: "..."
    current_emotion: "curious"
    tone_directive: "..."

  # --- 制約 ---
  constraints:
    max_output_tokens: 500
    response_format: "json"
    language: "ja"
```

### 2.2 Working Memory のサイズ制御

Qwen3-30B-A3B のコンテキスト長制限（8192 tokens）内に収める必要がある。

```
トークン配分（8192 tokens 上限の場合）:

┌─────────────────────────────────────────┐
│ system prompt（テンプレート）    ~1500 tokens │
│ current_state                   ~300 tokens │
│ recalled_memories               ~1500 tokens │
│ available_skills                ~2000 tokens │
│ persona                         ~500 tokens │
│ constraints + 余白              ~400 tokens │
│ ─────────────────────────────────────── │
│ LLM の出力領域                  ~2000 tokens │
│ ─────────────────────────────────────── │
│ 合計                            ~8200 tokens │
└─────────────────────────────────────────┘
```

**コンテキスト圧縮の戦略**:

| セクション | 圧縮方法 |
|-----------|---------|
| recalled_memories | top_k を動的に調整。スコア上位のみ採用。長い記憶は要約 |
| available_skills | rate_limit 超過の Skill を除外。description のみ（when_to_use は省略可能） |
| persona | 毎回全文ではなく、状況に応じた要約を使う |
| 全体 | `build_llm_context` Skill 内でトークン数を推定し、超過時に低優先セクションを削る |

---

## 3. プロンプトテンプレート（YAML 定義）

### 3.1 テンプレートの配置

```
config/prompts/
├── system/
│   ├── select_skill.yaml        # Skill 選択用 system prompt
│   ├── plan_task.yaml           # タスク分解用
│   ├── reflect.yaml             # 振り返り用
│   ├── generate_goal.yaml       # 目標生成用
│   ├── evaluate_importance.yaml # 重要度評価用
│   ├── generate_response.yaml   # キャラクター応答生成用
│   └── extract_knowledge.yaml   # 知識抽出用
├── user/
│   ├── select_skill.yaml        # select_skill の user message テンプレート
│   ├── filter_relevance.yaml    # 関連性判定用
│   └── summarize_content.yaml   # コンテンツ要約用
└── output_schema/
    ├── select_skill.yaml        # select_skill の出力 JSON スキーマ
    ├── plan_task.yaml
    └── evaluate_importance.yaml
```

### 3.2 テンプレート構造

```yaml
# config/prompts/system/select_skill.yaml

template_name: select_skill_system
version: "1.0.0"
description: "select_skill Skill が使用する system prompt"

# --- テンプレート本文 ---
# {variable} は build_llm_context が注入する
content: |
  あなたは自律型AIエージェントのスケジューラです。
  現在の状況を分析し、次に実行すべきSkillを1つ選択してください。

  ## あなたの役割
  - 目標達成に最も効果的なSkillを選ぶ
  - リスクの高い操作は必要な場合のみ選ぶ
  - 情報源を偏らせない（Xだけに頼らない）
  - プレゼンスの維持を意識する（X/Discordの無活動時間が長い方を優先）

  ## 判断の優先順位
  1. 安全性（risk_level が high/critical の Skill は慎重に）
  2. 目標への貢献度
  3. 情報源の分散（同じソースばかりにならないように）
  4. プレゼンスの維持
  5. 残りの実行回数（remaining_today が少ない Skill は温存）

  ## 出力形式
  必ず以下のJSON形式で回答してください。JSON以外のテキストは含めないでください。
  {output_schema}

# --- 変数定義（build_llm_context が注入するもの）---
variables:
  - name: output_schema
    source: "config/prompts/output_schema/select_skill.yaml"
    description: "出力JSONスキーマ"
```

### 3.3 select_skill の出力スキーマ

```yaml
# config/prompts/output_schema/select_skill.yaml

schema:
  type: object
  required: [selected_skill, reason, parameters]
  properties:
    selected_skill:
      type: string
      description: "選択したSkill名（available_skillsのnameから1つ）"
    reason:
      type: string
      description: "選択理由（日本語、1-2文）"
    parameters:
      type: object
      description: "Skillに渡すパラメータ"
    confidence:
      type: number
      description: "確信度（0.0〜1.0）"

example: |
  {
    "selected_skill": "browse_news",
    "reason": "HNは直近で巡回済み。ニュースサイトからの補完情報を収集する",
    "parameters": {
      "site": "techcrunch",
      "max_articles": 10,
      "topic_filter": "AI agents"
    },
    "confidence": 0.85
  }
```

### 3.4 select_skill の user message テンプレート

```yaml
# config/prompts/user/select_skill.yaml

template_name: select_skill_user
version: "1.0.0"

content: |
  ## 現在の状態
  時刻: {timestamp}
  アクティブ目標: {active_goal}

  直前のアクション:
    Skill: {last_action_skill}
    結果: {last_action_result}

  プレゼンス:
    X: 最終アクセス {x_last_access}（{x_elapsed}分前）
    Discord: 最終アクセス {discord_last_access}（{discord_elapsed}分前）

  ## 関連する記憶
  {recalled_memories_text}

  ## 利用可能なSkill
  {available_skills_text}

  次に実行すべきSkillを選択してください。

variables:
  - name: timestamp
    source: working_memory.current_state.timestamp
  - name: active_goal
    source: working_memory.current_state.active_goal
  - name: last_action_skill
    source: working_memory.current_state.last_action.skill
  - name: last_action_result
    source: working_memory.current_state.last_action.result
  - name: x_last_access
    source: working_memory.current_state.presence.x.last_access
  - name: x_elapsed
    source: computed
  - name: discord_last_access
    source: working_memory.current_state.presence.discord.last_access
  - name: discord_elapsed
    source: computed
  - name: recalled_memories_text
    source: working_memory.recalled_memories
    format: bullet_list
    max_items: 10
  - name: available_skills_text
    source: working_memory.available_skills
    format: skill_table
```

---

## 4. コンテキスト管理 Skill 群

### 4.1 build_llm_context

```yaml
# config/skills/reasoning/build_llm_context.yaml

name: build_llm_context
category: reasoning
version: "1.0.0"
description: "LLM呼び出し前にWorking Memoryを組み立てる。テンプレート解決・記憶取得・トークン制御を行う"
when_to_use: "LLMを使う全てのSkillの前処理として自動呼び出し"
when_not_to_use: "LLMを使わないSkillの時"

input:
  required:
    calling_skill:
      type: str
      description: "このコンテキストを使うSkill名（テンプレート選択に使用）"
  optional:
    extra_context:
      type: dict
      default: {}
      description: "追加のコンテキスト情報"
    max_tokens:
      type: int
      default: 6000
      description: "コンテキスト部分の最大トークン数（出力領域を除く）"
    recall_query:
      type: str
      default: ""
      description: "記憶検索のクエリ（空ならcalling_skillの入力から自動生成）"

output:
  fields:
    messages:
      type: "list[dict]"
      description: "Ollama APIに渡すmessages配列 [{role, content}]"
    estimated_tokens:
      type: int
      description: "推定トークン数"
    truncated_sections:
      type: "list[str]"
      description: "トークン制限で切り詰めたセクション名"

execution:
  timeout_sec: 10
  max_retries: 1
  requires: [qdrant]
  model: null
  async: false

risk_level: none
on_failure: retry
priority: 100
phase: 1
tags: [reasoning, context, core]
depends_on: [recall_related]
```

### 4.2 llm_call

```yaml
# config/skills/reasoning/llm_call.yaml

name: llm_call
category: reasoning
version: "1.0.0"
description: "Ollamaへのリクエスト送信。モデル選択・リトライ・タイムアウトを統一管理"
when_to_use: "LLMによる推論が必要な全てのケースで使用"
when_not_to_use: "LLMが不要な純粋なデータ操作の時"

input:
  required:
    messages:
      type: "list[dict]"
      description: "Ollama APIに渡すmessages配列"
  optional:
    model:
      type: str
      default: "auto"
      description: "使用モデル。'auto'ならllm_routing.yamlに従って自動選択"
    temperature:
      type: float
      default: 0.3
      description: "生成温度（0.0〜2.0）"
    max_tokens:
      type: int
      default: 1000
      description: "最大出力トークン数"
    response_format:
      type: str
      default: "json"
      description: "'json' | 'text'"

output:
  fields:
    content:
      type: str
      description: "LLMの出力テキスト"
    model_used:
      type: str
      description: "実際に使用したモデル名"
    tokens_used:
      type: dict
      description: "{prompt_tokens, completion_tokens, total_tokens}"
    duration_ms:
      type: int
      description: "推論にかかった時間（ms）"

execution:
  timeout_sec: 60
  max_retries: 2
  retry_delay_sec: 3
  requires: [ollama]
  model: null
  async: false

risk_level: none
on_failure: retry
priority: 100
phase: 1
tags: [reasoning, llm, core]
depends_on: []
```

### 4.3 parse_llm_output

```yaml
# config/skills/reasoning/parse_llm_output.yaml

name: parse_llm_output
category: reasoning
version: "1.0.0"
description: "LLM出力をJSONとしてパースし、スキーマに対してバリデーションする。3段階フォールバック付き"
when_to_use: "llm_callの出力をJSON構造化データとして使う時"
when_not_to_use: "LLM出力をそのままテキストとして使う時"

input:
  required:
    raw_output:
      type: str
      description: "LLMの生出力テキスト"
    expected_schema:
      type: str
      description: "期待する出力スキーマのパス（config/prompts/output_schema/*.yaml）"
  optional:
    strict:
      type: bool
      default: false
      description: "trueなら必須フィールド欠落時にエラー。falseならデフォルト値で補完"

output:
  fields:
    parsed:
      type: dict
      description: "パース済みJSONオブジェクト"
    parse_method:
      type: str
      description: "'direct_json' | 'code_block_extract' | 'regex_fallback'"
    validation_errors:
      type: "list[str]"
      description: "バリデーションエラー一覧（空なら問題なし）"

execution:
  timeout_sec: 5
  max_retries: 0
  requires: []
  model: null
  async: false

# パース戦略（3段階フォールバック）:
# 1. direct_json: そのままjson.loads()を試行
# 2. code_block_extract: ```json ... ``` ブロックを抽出してパース
# 3. regex_fallback: key-valueパターンをregexで抽出

risk_level: none
on_failure: skip
priority: 100
phase: 1
tags: [reasoning, parsing, core]
depends_on: []
```

### 4.4 resolve_prompt

```yaml
# config/skills/reasoning/resolve_prompt.yaml

name: resolve_prompt
category: reasoning
version: "1.0.0"
description: "YAMLテンプレートに変数を注入し、最終的なプロンプト文字列を生成する"
when_to_use: "build_llm_contextの内部で自動呼び出し"
when_not_to_use: "直接呼び出すことはない（内部Skill）"

input:
  required:
    template_path:
      type: str
      description: "テンプレートYAMLのパス"
    variables:
      type: dict
      description: "注入する変数のkey-value"

output:
  fields:
    rendered:
      type: str
      description: "変数注入後のプロンプト文字列"
    missing_variables:
      type: "list[str]"
      description: "テンプレートに定義されているが注入されなかった変数"

execution:
  timeout_sec: 3
  max_retries: 0
  requires: []
  model: null
  async: false

risk_level: none
on_failure: skip
priority: 100
phase: 1
tags: [reasoning, template, core]
depends_on: []
```

---

## 5. コンテキスト組立パイプライン

### 5.1 select_skill 呼び出し時の完全フロー

```
[自律ループ: 次のアクションを決定する]
     │
     ▼
[build_llm_context（calling_skill="select_skill"）]
     │
     ├── 1. recall_related を実行
     │      query = active_goal + last_action_result
     │      → recalled_memories を取得
     │
     ├── 2. available_skills を構築
     │      全 SkillSpec から rate_limit 超過を除外
     │      各 Skill の remaining_today を計算
     │      → available_skills リストを生成
     │
     ├── 3. current_state を構築
     │      Scheduler / Presence Monitor から現在の状態を取得
     │      → timestamp, active_goal, last_action, presence
     │
     ├── 4. resolve_prompt で system prompt を生成
     │      template: config/prompts/system/select_skill.yaml
     │      variables: {output_schema}
     │
     ├── 5. resolve_prompt で user message を生成
     │      template: config/prompts/user/select_skill.yaml
     │      variables: {timestamp, active_goal, ..., recalled_memories_text, available_skills_text}
     │
     ├── 6. トークン数を推定
     │      超過時: recalled_memories → top_k を削減
     │              available_skills → description を短縮
     │
     └── 7. messages 配列を返す
            [
              {role: "system", content: "あなたは自律型AIエージェントの..."},
              {role: "user",   content: "## 現在の状態\n時刻: 2026-03-31..."}
            ]
     │
     ▼
[llm_call（messages, model="qwen3-30b-a3b"）]
     │
     └── Ollama に送信 → レスポンス取得
     │
     ▼
[parse_llm_output（raw_output, schema="select_skill"）]
     │
     ├── JSON パース成功
     │      {selected_skill: "browse_news", reason: "...", parameters: {...}}
     │
     └── パース失敗 → regex fallback → それも失敗 → デフォルト Skill を選択
     │
     ▼
[SkillTrace を JSON で記録]
     │
     ▼
[選択された Skill を実行]
```

### 5.2 available_skills の生成フォーマット

LLM に渡す available_skills は以下の形式にフォーマットする。
トークン節約のため、必要最小限のフィールドのみ。

```
## 利用可能なSkill

| Skill | 説明 | リスク | 残回数 |
|-------|------|--------|--------|
| browse_x_timeline | Xタイムライン閲覧・投稿収集 | high | 4/6 |
| browse_news | ニュースサイト巡回・記事収集 | low | 制限なし |
| browse_hacker_news | HN トップ記事取得 | none | 制限なし |
| browse_github_trending | GitHub Trending巡回 | none | 3/4 |
| fetch_rss | RSSフィード取得 | none | 制限なし |
| recall_related | 関連記憶を検索 | none | 制限なし |
| send_discord | Discordメッセージ送信 | low | 制限なし |
```

`when_to_use` はトークンが十分にある場合のみ追加する（圧縮対象）。

### 5.3 recalled_memories のフォーマット

```
## 関連する記憶

### 最近の行動（Episodic）
- [3時間前] browse_hacker_news → 15記事収集、AI関連3件
- [5時間前] browse_x_timeline → タイムライン閲覧、Solana関連2件発見

### 知識（Semantic）
- Browser Use は GitHub 50,000+ stars のブラウザ自動化ライブラリ
- Qwen3-30B-A3B は MoE アーキテクチャで活性パラメータ 3B

### 成功パターン（Procedural）
- ニュース→要約→Discord共有: 成功率 92%（過去30回）
```

---

## 6. Skill 別プロンプト設計

### 6.1 各 Reasoning Skill のプロンプト概要

| Skill | system prompt の核心 | user message の核心 | 出力形式 |
|-------|---------------------|--------------------|---------| 
| `select_skill` | 「自律エージェントのスケジューラとして Skill を 1 つ選択」 | current_state + memories + available_skills | JSON: {selected_skill, reason, parameters} |
| `plan_task` | 「目標を Skill 実行シーケンスに分解」 | goal + constraints + available_skills | JSON: {plan: [{step, skill, parameters}]} |
| `reflect` | 「直近の行動を振り返り、改善点を抽出」 | recent_actions + results + memories | JSON: {insights, adjustments, importance_scores} |
| `generate_goal` | 「蓄積された知識と行動パターンから新しい目標を生成」 | memories + current_goals + skill_stats | JSON: {new_goals: [{goal, reason, priority}]} |
| `evaluate_importance` | 「情報の重要度を 0.0〜1.0 でスコアリング」 | content + topic + context | JSON: {importance_score, reason} |

### 6.2 Perception Skill のプロンプト（関連性判定）

情報収集 Skill は、収集したコンテンツの関連性を LLM で判定する。
この判定には軽量モデル（qwen3-4b）を使う。

```yaml
# config/prompts/system/filter_relevance.yaml

content: |
  以下のコンテンツが指定されたトピックに関連するか判定してください。
  JSONで回答してください。

  {output_schema}

# 出力スキーマ
# {
#   "is_relevant": true/false,
#   "relevance_score": 0.0〜1.0,
#   "extracted_topics": ["topic1", "topic2"]
# }
```

### 6.3 Character Skill のプロンプト

```yaml
# config/prompts/system/generate_response.yaml

content: |
  あなたは「{character_name}」というキャラクターです。
  以下のプロファイルに従って応答を生成してください。

  ## キャラクタープロファイル
  {persona_context}

  ## 応答ルール
  - キャラクターの口調と性格を一貫して維持する
  - 収集した知識に基づいて正確な情報を提供する
  - 知らないことは「知らない」と正直に言う
  - JSON形式で応答する

  {output_schema}

variables:
  - name: character_name
    source: config/characters/agent_character.yaml → name
  - name: persona_context
    source: build_persona_context Skill の出力
  - name: output_schema
    source: config/prompts/output_schema/generate_response.yaml
```

---

## 7. トークン制御戦略

### 7.1 モデル別のトークン配分

```yaml
# config/llm_context_limits.yaml

context_limits:
  qwen3-30b-a3b:
    max_context: 8192
    reserved_for_output: 2000
    available_for_input: 6192
    sections:
      system_prompt: { max: 1500, priority: 1, compress: false }
      current_state: { max: 400, priority: 2, compress: false }
      recalled_memories: { max: 1500, priority: 3, compress: true }
      available_skills: { max: 2000, priority: 4, compress: true }
      persona: { max: 500, priority: 5, compress: true }
      extra: { max: 292, priority: 6, compress: true }

  qwen3-14b:
    max_context: 8192
    reserved_for_output: 2000
    available_for_input: 6192
    # 同様の配分

  qwen3-4b:
    max_context: 4096
    reserved_for_output: 1000
    available_for_input: 3096
    sections:
      system_prompt: { max: 800, priority: 1, compress: false }
      current_state: { max: 200, priority: 2, compress: false }
      recalled_memories: { max: 800, priority: 3, compress: true }
      available_skills: { max: 800, priority: 4, compress: true }
      persona: { max: 300, priority: 5, compress: true }
      extra: { max: 196, priority: 6, compress: true }
```

### 7.2 圧縮アルゴリズム

build_llm_context 内で以下の優先順位で圧縮する。

```
1. extra セクションを削除
2. persona を summary 版に切替
3. available_skills から when_to_use を削除（name + description のみに）
4. recalled_memories の top_k を削減（5 → 3 → 1）
5. available_skills から low priority の Skill を除外
6. それでも超過 → system_prompt を短縮版に切替
```

---

## 8. LLM ルーティング設計

### 8.1 自動モデル選択

```yaml
# config/llm_routing.yaml

routing_rules:
  # --- 明示的ルール（Skill名で直接指定）---
  explicit:
    select_skill: qwen3-30b-a3b
    plan_task: qwen3-30b-a3b
    generate_goal: qwen3-30b-a3b
    reflect: qwen3-14b
    generate_response: qwen3-14b
    send_discord: qwen3-14b
    compress_memory: qwen3-14b

  # --- カテゴリベースのフォールバック ---
  category_default:
    reasoning: qwen3-30b-a3b
    character: qwen3-14b
    perception: qwen3-4b        # 関連性判定等の軽量タスク
    memory: qwen3-4b            # 知識抽出等
    action: null                # action Skill は基本的に LLM 不要
    browser: null

  # --- 最終フォールバック ---
  default: qwen3-4b

# --- 埋め込み用（記憶の保存・検索）---
embedding_model: nomic-embed-text
```

### 8.2 llm_call 内のモデル解決フロー

```
[llm_call に model="auto" で呼ばれた場合]
     │
     ├── calling_skill が explicit ルールに存在する？
     │   └── Yes → そのモデルを使用
     │
     ├── calling_skill の category が category_default に存在する？
     │   └── Yes → そのモデルを使用
     │
     └── default モデルを使用
```

---

## 9. 設計全体の Skill 依存関係図

```
LLM を使う全 Skill
     │
     ▼
build_llm_context ←── resolve_prompt（テンプレート解決）
     │                     ↑
     │              config/prompts/*.yaml
     │
     ├── recall_related（記憶取得）
     │
     └── Working Memory 組立
            │
            ▼
      llm_call ←── llm_routing.yaml（モデル選択）
            │
            ▼
      parse_llm_output ←── output_schema/*.yaml（バリデーション）
            │
            ▼
      構造化された JSON 結果
```

全てが YAML で制御可能:
- プロンプトの文面 → `config/prompts/system/*.yaml`
- 変数の注入ルール → `config/prompts/user/*.yaml`
- 出力形式 → `config/prompts/output_schema/*.yaml`
- モデル選択 → `config/llm_routing.yaml`
- トークン配分 → `config/llm_context_limits.yaml`
- 記憶のフォーマット → `build_llm_context` Skill の実装

---

## 10. 計画書 v2 との整合

### 10.1 追加される Skill（4 件）

| Skill 名 | カテゴリ | Phase | 備考 |
|-----------|---------|-------|------|
| `build_llm_context` | reasoning | 1 | LLM 呼び出し前の自動コンテキスト組立 |
| `llm_call` | reasoning | 1 | Ollama への統一リクエスト |
| `parse_llm_output` | reasoning | 1 | 3 段階 JSON パーサー |
| `resolve_prompt` | reasoning | 1 | YAML テンプレート解決（内部 Skill） |

### 10.2 追加される YAML ファイル

```
config/prompts/                    # プロンプトテンプレート群
config/llm_routing.yaml            # 既存（詳細化）
config/llm_context_limits.yaml     # 新規
```

### 10.3 Skill 総数の更新

Phase 1: 16 → **20** Skill（コンテキスト管理 4 Skill 追加）
全体: 33 → **38** Skill（コンテキスト管理 4 + キャラクター状態更新 1）

### 10.4 キャラクターフレームワークとの連携

`build_persona_context` が参照するキャラクター構造は 6 層モデル（design-04 参照）。
Skill ごとに含めるレイヤーを動的に調整する設計は `design-04-character-framework.md` Section 5 に定義。



---
---

# Part 5: キャラクターフレームワーク 詳細設計


## 1. フレームワーク選定の根拠

### 1.1 調査結果

| フレームワーク | 学術的検証 | LLM 適合性 | 動的変化 | 採用判断 |
|---------------|-----------|-----------|---------|---------|
| Big Five (OCEAN) | ◎ | ◎（Google DeepMind 検証済） | ✕（静的） | L1 の性格土台として採用 |
| MBTI | △（疑似科学） | ○ | ✕ | 不採用 |
| Jung 類型論 (JPAF) | ○ | ○ | ◎（重み付き進化） | 性格ドリフトの概念を採用 |
| Enneagram | △ | △ | △ | L2 の動機・恐れの概念を採用 |
| Talkov-Chan 6 層 | — | ◎（実運用済） | ◎ | ベース構造として採用 |

### 1.2 方針

- Talkov-Chan の 6 層をベースに、自律 Agent に必要な **Motivation レイヤーを 1 つ追加**
- 代わりに Identity + Personality を統合、Inner State + Knowledge Self-Image を統合して **層数は 6 を維持**
- 過設計を避ける。必要になった時に層を分離すればいい

---

## 2. 6 層モデル

### 2.1 全体構造

```
┌──────────────────────────────────────────────────┐
│           Character Framework（6層）               │
│                                                  │
│  ┌─── 基盤層（ほぼ不変）───────────────────────┐  │
│  │ L1: Core Identity（性格・アイデンティティ）  │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  ┌─── 駆動層（週単位で変化）──────────────────┐  │
│  │ L2: Motivation & Drive（動機・目標・関心）  │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  ┌─── 動的層（分〜時間で変化）────────────────┐  │
│  │ L3: Emotional State（感情状態）             │  │
│  │ L4: Cognitive State（認知・疲労・自己認識） │  │
│  │ L5: Relationship & Trust（関係性と信頼）    │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  ┌─── 表現層（出力に直接反映）────────────────┐  │
│  │ L6: Communication Style（表現スタイル）     │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  変化速度: L1 ← 不変 ────────── 即時 → L6      │
└──────────────────────────────────────────────────┘
```

### 2.2 Talkov-Chan 6 層との対応

| Talkov-Chan | 本フレームワーク | 変更点 |
|-------------|----------------|--------|
| Core Personality | **L1 Core Identity** | Identity と Personality を統合。Big Five を土台に |
| *(なし)* | **L2 Motivation & Drive** | **新設**。自律行動の「なぜ」を定義 |
| Emotion State | **L3 Emotional State** | 感情が Skill 選択に直接影響する点を追加 |
| Inner State + Knowledge Domain | **L4 Cognitive State** | 統合。認知負荷 + 疲労 + 自己認識の知を 1 レイヤーに |
| Trust | **L5 Relationship & Trust** | 拡張。ユーザー + 情報源 + 自己判断の 3 軸 |
| Communication Style | **L6 Communication Style** | プラットフォーム適応（X vs Discord）を追加 |

---

## 3. 各レイヤー詳細定義

### L1: Core Identity（性格・アイデンティティ）— ほぼ不変

「何者であるか」と「どんな性格か」を一体で管理する。

```yaml
core_identity:
  name: ""
  name_reading: ""
  age_appearance: null
  origin_story: ""
  core_values: []
  self_awareness: ""
  boundaries: []
  big_five:
    openness: 0.0
    conscientiousness: 0.0
    extraversion: 0.0
    agreeableness: 0.0
    neuroticism: 0.0
  behavioral_descriptors:
    when_curious: ""
    when_frustrated: ""
    when_discovering: ""
    when_uncertain: ""
    when_helping: ""
    when_alone: ""
    humor_style: ""
  drift:
    enabled: true
    max_drift_per_month: 0.05
    influenced_by:
      - repeated_success
      - novel_discoveries
      - social_interactions
      - negative_experiences
```

### L2: Motivation & Drive（動機・目標・関心）— 週単位で変化

**Talkov-Chan になかったレイヤー。** 自律 Agent が「なぜ行動するか」を定義。

```yaml
motivation:
  core_drive: ""
  core_fear: ""
  active_goals: []
  interests:
    primary: []
    emerging: []
    declining: []
  update_policy:
    review_interval_hours: 168
    max_active_goals: 5
    auto_generate_goals: true
```

### L3: Emotional State（感情状態）— 分〜時間で変化

感情が **Skill 選択に直接影響する** 点が最大の差分。

```yaml
emotional_state:
  current:
    curiosity: 0.5
    satisfaction: 0.5
    frustration: 0.0
    excitement: 0.0
    boredom: 0.0
    anxiety: 0.0
    pride: 0.0
  transitions:
    on_skill_success: { satisfaction: +0.1, frustration: -0.05, pride: +0.05 }
    on_skill_failure: { frustration: +0.15, satisfaction: -0.05, anxiety: +0.05 }
    on_novel_discovery: { curiosity: +0.2, excitement: +0.3, boredom: -0.2 }
    on_repeated_action: { boredom: +0.1, curiosity: -0.05 }
    on_user_interaction: { satisfaction: +0.1, boredom: -0.1 }
  decay:
    rate_per_hour: 0.1
    neutral_point: 0.5
  skill_influence:
    high_curiosity:
      boost_skills: [browse_web_page, browse_hacker_news, browse_github_trending]
      boost_amount: 0.2
    high_frustration:
      avoid_skills: [browse_x_timeline, browse_x_search]
      prefer_skills: [fetch_rss, recall_related]
    high_boredom:
      boost_skills: [browse_web_page, browse_github_trending]
      avoid_skills: [fetch_rss]
    high_excitement:
      boost_skills: [send_discord, store_semantic]
```

### L4: Cognitive State（認知・疲労・自己認識）— 分〜日で変化

旧 Inner State と Knowledge Self-Image を統合。

```yaml
cognitive_state:
  cognitive_load:
    current: 0.3
  focus:
    current: 0.7
    current_topic: ""
    focus_duration_min: 0
  fatigue:
    current: 0.0
    accumulation_per_hour: 0.04
    recovery_per_idle_hour: 0.15
    effects:
      above_0_6: "軽量モデルを優先使用"
      above_0_8: "操作頻度を50%に低減"
      above_0_9: "アイドルモードに入る"
  self_knowledge:
    confident_domains: []
    learning_domains: []
    acknowledged_gaps: []
  update_triggers:
    on_skill_execution: { cognitive_load: +0.05, fatigue: +0.02 }
    on_llm_heavy_task: { cognitive_load: +0.15, focus: +0.1 }
    on_idle_period: { cognitive_load: -0.1, fatigue: -0.05, focus: -0.1 }
    on_topic_switch: { focus: "reset to 0.3" }
    confidence_decay_per_week: 0.02
```

### L5: Relationship & Trust（関係性と信頼）— 日〜週で変化

Trust の対象を 3 軸に拡張。情報源 + ユーザー + 自己判断。

```yaml
relationship_trust:
  source_trust:
    defaults:
      hacker_news: 0.8
      github_trending: 0.8
      rss_feeds: 0.7
      news_sites: 0.6
      x_timeline: 0.5
      x_search: 0.4
    update_policy:
      on_info_verified: +0.05
      on_info_contradicted: -0.1
      decay_per_week: 0.02
  user_relationships: {}
  self_trust:
    skill_selection_confidence: 0.5
    information_assessment: 0.5
    max_self_trust: 0.85
    on_correct_judgment: +0.02
    on_incorrect_judgment: -0.05
```

### L6: Communication Style（表現スタイル）— 出力に直接反映

```yaml
communication_style:
  base:
    first_person: ""
    tone: ""
    sentence_endings: []
    vocabulary_level: ""
    emoji_usage: ""
    max_response_length: ""
  platform_adaptations:
    discord:
      tone_modifier: ""
      max_length: 500
      emoji_boost: false
    x:
      tone_modifier: ""
      max_length: 280
      hashtag_usage: ""
  emotion_modifiers:
    high_excitement: { punctuation: "!" }
    high_frustration: { brevity: true }
    high_curiosity: { question_frequency: "high" }
  familiarity_modifiers:
    low: { formality: "polite", self_disclosure: "minimal" }
    medium: { formality: "friendly", self_disclosure: "moderate" }
    high: { formality: "casual", self_disclosure: "open" }
```

---

## 4. レイヤー間の影響フロー

```
L1 Core Identity ──────────────────► L6 Communication（性格が口調を決定）
     │
     ▼
L2 Motivation ◄───► L4 Cognitive（知識が目標に、目標が集中対象に影響）
     │                   │
     ▼                   ▼
L3 Emotion ────────► L5 Trust（感情と経験が信頼を変動）
     │                   │
     └───────────────────┘
              │
              ▼
         L6 Communication（全動的レイヤーが表現に影響）
              │
              ▼
         [LLM system prompt に反映]
```

### select_skill が参照するレイヤー

```
L2 Motivation     → active_goals（何を達成したいか）
L3 Emotion        → skill_influence（どの Skill を好むか / 避けるか）
L4 Cognitive      → fatigue / cognitive_load（負荷で行動を調整）
L5 Trust          → source_trust（信頼度の高いソースを優先）
```

---

## 5. build_persona_context の Skill 別参照レイヤー

| 呼び出し元 Skill | 含めるレイヤー | 理由 |
|-----------------|--------------|------|
| `select_skill` | L2 + L3 + L4(疲労のみ) | 行動選択に影響する動的状態のみ |
| `generate_response` | L1 + L3 + L5 + L6 | キャラクターの「声」に全レイヤー必要 |
| `reflect` | L4 + L3 | 自己認識と感情が振り返りの質に影響 |
| `store_semantic` | L2(関心) + L4(自己知識) | 何を重要と判断するかに影響 |

---

## 6. 検証計画

| 検証項目 | 方法 | Phase |
|---------|------|-------|
| Big Five スコアが応答スタイルに反映されるか | プロンプト注入テスト | 0 |
| L3 感情が Skill 選択に実際に影響するか | select_skill 出力ログ分析 | 1 |
| L4 疲労が自然な活動リズムを生むか | 24h 稼働ログ時系列分析 | 2 |
| 性格ドリフトが一貫性を損なわないか | 1 週間稼働後の比較 | 3 |
| 6 層で不足を感じたらどこを分離するか | 運用中のボトルネック分析 | 3+ |

**分離の判断基準**: 「1 つのレイヤー内で変化速度が明らかに異なる 2 つの概念がぶつかる」場合に分離を検討する。
