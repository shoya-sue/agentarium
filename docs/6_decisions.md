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
| D12 | ブラウザソース運用 | google_news/newspicks 有効 | **google_news 無効化・newspicks 無効化** | JS難読化/ログイン必須で取得不可。Google News は RSS 代替 |
| D13 | RSS情報源選定 | TechCrunch/hnrss.org 含む旧構成 | **高S/N比10フィードに刷新** | ノイズ源除外、Qiita/Zenn/はてブIT/Publickey/Lobsters/Ars Technica 追加 |

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

---

## D12: ブラウザソース運用 — google_news/newspicks 無効化

### 背景

Phase 0 実装中にブラウザ取得の実用性を検証した結果、2ソースで取得不可能と判明。

### 検証結果

| ソース | 問題 | 対応 |
|--------|------|------|
| google_news | JS完全レンダリングSPA。`networkidle` 後でも `article`/`h3` 等の意味的HTML要素が存在しない。ボディは2.4MBだがスクレイピング不可 | `enabled: false`。Google News RSSを`rss_feeds.yaml`に追加して代替 |
| newspicks | ログイン必須。認証なしでは記事リストが取得できない | `enabled: false`。Phase 2 で Cookie 認証実装後に再有効化 |

### Chromium 安定化フラグ（同時対応）

Docker コンテナ内で `/dev/shm` 共有メモリ不足（デフォルト 64MB）による `Page crashed` が発生。
`docker-compose.yml` に以下のフラグを追加して解消：

```
--disable-dev-shm-usage   # /dev/shm → /tmp に切り替え
--disable-gpu             # GPU レンダリング無効化
--no-zygote               # プロセス分岐を抑制
```

### Yahoo News セレクタ修正（同時対応）

`.newsFeed_item` クラスが廃止されており 0件 を返していた。
ライブDOM確認により `.newsFeed_list > li` に更新（50件確認）。
`wait_for: networkidle` + `wait_for_selector` を追加してJS レンダリング待機を確実化。

### 有効ソース（修正後）

| ソース | 取得方式 | 間隔 | 取得件数 |
|--------|---------|------|---------|
| rss_feeds | RSS直接取得 | 60分 | 20件 |
| hacker_news | Firebase API | 60分 | 20件 |
| yahoo_news | ブラウザ（Stealth不要） | 120分 | 20件 |
| github_trending | ブラウザ（Stealth不要） | 360分 | 14件 |

---

## D13: RSS情報源刷新 — 高S/N比10フィードへの再選定

### 背景

初期構成にTechCrunch（広告・ノイズ多）とhnrss.org/frontpage（HN APIと重複）が含まれており効率が悪かった。
google_news のブラウザ取得不可（D12）を機に、RSS全体を高S/N比視点で再設計。

### 選定基準

1. **S/N比**: 広告・クリックベイト・重複記事が少ない
2. **コミュニティフィルタ**: 人気順・ブックマーク数等で自動審査済みのもの優先
3. **多層化**: 日本語dev / 日本語ニュース / 英語dev の3カテゴリ横断
4. **キャラクター親和性**: Zephyr（発見・好奇心）・Lynx（深度・根拠）の両方に対応

### 採用フィード（10件）

| フィード | カテゴリ | 言語 | 採用理由 |
|---------|---------|------|---------|
| Qiita popular-items | tech_community | ja | 国内最大dev。人気順 = コミュニティ審査済み |
| Zenn | tech | ja | Qiitaと相補的。技術同人書に近い深さ |
| はてブ IT hotentry | tech_community | ja | 集合知フィルター。速報性＋キュレーション品質が両立 |
| Publickey | tech | ja | クラウド/OSS/AI の国内解説。1人編集者による高品質 |
| Gigazine | tech | ja | 日本語テック/科学の幅広カバー（速報性重視） |
| Google News RSS | news | ja | D12 でのブラウザ代替。主要ニュース網羅 |
| Yahoo News top-picks | news | ja | 国内ニュース全般 |
| Lobsters | tech_community | en | HN招待制版。技術深度はHN以上、ノイズはHN以下 |
| Ars Technica | tech | en | 長文技術ジャーナリズム。AI/セキュリティの深堀り |
| The Verge | tech | en | Big Tech速報。コンシューマーテック動向のカバー |

### 除外フィード

| フィード | 除外理由 |
|---------|---------|
| TechCrunch | 広告記事・スポンサーコンテンツが多く S/N 比が低い |
| hnrss.org/frontpage | HN API（hacker_news ソース）と完全重複 |

### 将来候補（Phase 1 以降で追加検討）

| フィード | 理由 |
|---------|------|
| arXiv cs.AI/cs.LG | ML/AI論文の一次情報。毎日更新。研究文脈の強化 |
| Dev.to | 英語dev。Qiitaの英語版的立ち位置 |
| MIT Technology Review | 技術の社会的影響まで踏み込む長文記事 |
| Reddit r/MachineLearning | 研究者コミュニティ。論文議論が活発 |
