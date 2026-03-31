# 設計レビュー・意思決定ログ

**レビュー日**: 2026-03-31
**対象**: 統合設計書 v1（1_agentarium_design.md）
**ステータス**: レビュー完了、意思決定反映待ち

---

## 意思決定サマリー

| # | 項目 | 元設計 | 決定 | 理由 |
|---|------|--------|------|------|
| D1 | LLMモデル | Qwen3-30B-A3B | **Qwen3.5-35B-A3B** | ベンチ向上、コンテキスト262K、劣化0.9% |
| D2 | LLMバックエンド | Ollama | **Phase 0 で MLX vs Ollama を検証** | MLX は約2倍速（M4系） |
| D3 | Skill設計 | 38 Skill（Phase 1: 20） | **アダプタパターンで統合（Phase 1: 10）** | 機能同等、実装量半減 |
| D4 | Skill選択 | LLM駆動（select_skill） | **Phase 1: ルールベース → Phase 2: LLM駆動** | 巡回パターンは予測可能 |
| D5 | コンテキスト長 | 8192 tokens | **16384+ tokens** | Qwen3.5は262Kサポート、圧縮負担軽減 |
| D6 | 圧縮戦略 | 6段階 | **2段階（Phase 1）** | cooldownフィルタ + memories top_k のみ |
| D7 | Qdrantコレクション | 4（episodic/semantic/procedural/character） | **2（episodic/semantic）** | procedural/characterはPhase 2-3 |
| D8 | メモリ管理 | Write-Manage-Read | **Write-Read + TTL自動削除** | compress/forgetはPhase 3以降 |
| D9 | キャラクター | 6層全実装 | **L1+L6 静的値のみ（Phase 1）** | 動的層はPhase 2-3 |
| D10 | 埋め込みモデル | nomic-embed-text | **Phase 0 で日本語品質検証** | multilingual-e5系を候補追加 |
| D11 | X検証優先度 | Phase 0 主要項目 | **Phase 0 後半に移動** | コアパイプライン構築を優先 |

---

## D1: LLMモデル — Qwen3 → Qwen3.5

### 背景

設計書作成時点（2026-03-31）では Qwen3-30B-A3B を前提としていたが、2026-02-24 に Qwen3.5-35B-A3B がリリース済み。

### 比較

| 項目 | Qwen3-30B-A3B | Qwen3.5-35B-A3B |
|------|---------------|-----------------|
| 総パラメータ | 30.5B | 35B |
| 活性パラメータ | 3.3B | 3B |
| コンテキスト長 | 131K | **262K** |
| MMLU-Pro | ~83 | **85.3** |
| GPQA Diamond | - | **84.2** |
| コンテキストスケーリング劣化(8K) | 21.5% | **0.9%** |
| アーキテクチャ | 標準MoE | **Gated DeltaNet hybrid**（256 experts） |
| M4 Max (MLX) | ~100 tok/s | 60-70+ tok/s |

### 決定

Qwen3.5-35B-A3B を採用。コンテキスト長の大幅拡張と劣化率の改善が最大のメリット。

### 影響範囲

- `config/llm_routing.yaml`: モデル名を `qwen3.5-35b-a3b` に変更
- `config/llm_context_limits.yaml`: コンテキスト上限を 16384+ に拡張
- VRAM 使用量: ほぼ同等（~18GB）

---

## D2: LLMバックエンド — Ollama vs MLX

### 背景

Apple Silicon では MLX バックエンドが Ollama（llama.cpp）の約2倍高速。

| バックエンド | 速度（Qwen3.5-35B-A3B Q4） | メリット | デメリット |
|------------|---------------------------|---------|-----------|
| Ollama | ~35 tok/s | エコシステム成熟、Docker連携容易 | 速度が遅い |
| MLX (mlx-lm) | 60-70+ tok/s | 高速、Apple最適化 | Docker内からの呼び出しが複雑 |

### 決定

Phase 0 で両方を検証し、速度とDocker連携の容易さで判断。

---

## D3: Skill設計 — アダプタパターンによる統合

### 背景

元設計では browse_news / browse_hacker_news / browse_github_trending 等が独立Skillとして定義されている。全て「ソースから情報を取得し統一JSONで返す」という共通パターン。

### 決定: 共通基盤 + ソースアダプタ

```
browse_source (1つのSkill)
  │
  ├── 共通処理: navigate → scroll → extract → JSON変換
  │
  └── config/sources/*.yaml (ソースアダプタ設定)
        ├── yahoo_news.yaml:
        │     url: "https://news.yahoo.co.jp"
        │     type: browser
        │     selectors: { article: ".newsFeed_item", title: "..." }
        ├── google_news.yaml
        ├── newspicks.yaml
        ├── hacker_news.yaml:
        │     type: api  ← ブラウザ不要
        │     url: "https://hacker-news.firebaseio.com/v0/"
        ├── github_trending.yaml
        ├── rss.yaml:
        │     type: rss  ← ブラウザ不要
        └── x_timeline.yaml:
              type: browser_stealth  ← Stealth必要
              requires: [stealth, human_behavior]
```

### メリット

- Skill数削減（5+ → 1）
- 新サイト追加 = YAML 1ファイル追加のみ
- テスト対象が1つの共通ロジックに集約
- 全サイトで同じブラウザコンテナを共有

### 低レベル操作の内部化

`click_element` / `navigate_to` / `scroll_page` は独立Skillではなく、browse_source 内部のユーティリティ関数に移動。LLMの選択候補から除外。

### Phase 1 MVP Skill一覧（10 Skill）

| # | Skill | カテゴリ | LLM | 備考 |
|---|-------|---------|-----|------|
| 1 | `browse_source` | perception | qwen3.5-4b（関連性判定のみ） | 統合Skill + ソースアダプタ |
| 2 | `fetch_rss` | perception | 不要 | browse_sourceに統合も可能だが、ブラウザ不要なので分離 |
| 3 | `store_episodic` | memory | 不要 | 行動ログ保存 |
| 4 | `store_semantic` | memory | qwen3.5-4b | 知識抽出・保存 |
| 5 | `recall_related` | memory | 不要 | ベクトル検索 |
| 6 | `llm_call` | reasoning | — | Ollama/MLX統一インターフェース |
| 7 | `parse_llm_output` | reasoning | 不要 | JSONパーサー |
| 8 | `resolve_prompt` | reasoning | 不要 | テンプレート解決 |
| 9 | `human_behavior` | browser | 不要 | 操作の人間化 |
| 10 | `verify_x_session` | browser | 不要 | Xセッション確認 |

スケジューラはルールベース（cron的巡回）。

---

## D4: Skill選択 — Phase 1 ルールベース → Phase 2 LLM駆動

### 背景

元設計では毎ループで select_skill → build_llm_context → recall_related → resolve_prompt → llm_call → parse_llm_output の6 Skillチェーンが走る。Phase 1 の情報収集巡回は予測可能なパターン。

### Phase 1: ルールベーススケジューラ

```python
# config/schedules/patrol.yaml で定義
patrol:
  - source: hacker_news
    interval_min: 60
  - source: rss_feeds
    interval_min: 60
  - source: news_sites
    interval_min: 120
  - source: github_trending
    interval_min: 360
  - source: x_timeline       # Phase 0 Go判定後に有効化
    interval_min: 180
    enabled: false
```

### Phase 2: LLM駆動に移行

Phase 2 でキャラクターとDiscord応答が追加されると、「情報収集 vs Discord応答 vs 知識整理」の優先度判断が必要になり、LLM駆動の select_skill が価値を発揮する。

---

## D5-D6: コンテキスト管理の簡素化

### コンテキスト長: 8192 → 16384+

Qwen3.5-35B-A3B は 262K コンテキストをサポート。OLLAMA_NUM_CTX=16384 にしても VRAM 増加は ~2GB。余裕を持たせることで圧縮戦略の実装負担を大幅軽減。

### 圧縮戦略: 6段階 → 2段階（Phase 1）

| Phase 1 で実装 | Phase 2+ で追加 |
|---------------|----------------|
| cooldown中のSkill除外 | persona短縮版 |
| recalled_memories top_k削減 | Skill when_to_use削除 |
| | extra削除 |
| | system_prompt短縮版 |

---

## D7-D8: 記憶システムの段階的構築

### Qdrant: 4 → 2コレクション

| コレクション | Phase 1 | Phase 2 | Phase 3 |
|------------|---------|---------|---------|
| episodic | ✅ | ✅ | ✅ |
| semantic | ✅ | ✅ | ✅ |
| procedural | — | ✅ | ✅ |
| character | — | — | ✅ |

### メモリ管理: TTL自動削除のみ

Phase 1-2 では蓄積データが数百〜数千ポイント。Qdrant のパフォーマンスは問題にならない。compress_memory / forget_low_value は Phase 3 で蓄積量が問題になってから実装。

---

## D9: キャラクター — 段階的導入

| レイヤー | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|---------|---------|---------|---------|---------|
| L1 Core Identity | 静的値のみ | ✅ | ✅ | ドリフト有効化 |
| L2 Motivation | — | 静的goals | 動的goals | ✅ |
| L3 Emotional State | — | — | ルールベース | ✅ |
| L4 Cognitive State | — | — | 疲労モデル | ✅ |
| L5 Relationship & Trust | — | — | source_trust | ✅ |
| L6 Communication Style | base のみ | platform適応 | emotion修飾 | ✅ |

---

## D10: 埋め込みモデル — 日本語検証

### Phase 0 検証項目に追加

| モデル | パラメータ | 日本語 | VRAM | 検証内容 |
|--------|-----------|--------|------|---------|
| nomic-embed-text | 137M | 弱 | ~0.3GB | ベースライン |
| multilingual-e5-base | 278M | 良好 | ~0.6GB | 日本語混在テキストの類似度 |
| multilingual-e5-large | 560M | 良好 | ~1.1GB | 品質上限の確認 |

テストケース: 日英混在の技術文書（「Qwen3.5はMoEアーキテクチャ」等）で類似度検索の精度を比較。

---

## D11: Phase 0 の再構成

### 元設計のPhase 0

X検証が中心で、コアパイプラインの検証が薄い。

### 改訂版 Phase 0

```
Phase 0 前半（1週目）: コアパイプライン検証
  ├── Qwen3.5-35B-A3B の推論速度・JSON出力品質
  ├── Ollama vs MLX ベンチマーク
  ├── 埋め込みモデル日本語検証
  ├── SkillSpec YAML → dataclass ロード基盤
  ├── Qdrant 基本パイプライン（保存・検索）
  └── 代替ソース検証（HN API / GitHub / RSS）

Phase 0 後半（2週目）: ブラウザ・X検証
  ├── Docker内 Playwright Stealth テスト
  ├── bot.sannysoft.com / browserscan.net パス確認
  ├── X セッション維持テスト
  ├── X タイムライン閲覧テスト
  └── Go / No-Go 判定
```

コアパイプラインが動くことを先に確認し、X検証の結果に関わらずPhase 1に進めるようにする。
