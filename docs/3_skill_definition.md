# Part 3: Skill 定義 + YAML テンプレート 詳細設計

> **改訂**: 設計レビュー（6_decisions.md D3/D4）に基づき、アダプタパターンを採用。browse 系 Skill を共通基盤 `browse_source` + ソースアダプタ YAML に統合。低レベルブラウザ操作は Skill から除外しユーティリティ関数化。Phase 1 のSkill選択はルールベーススケジューラ。

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

全 Skill を一覧する。各 Skill の詳細 YAML は Section 3 以降で定義。

### 2.1 サマリーテーブル

**Phase 1 Skill（10 Skill）**:

| # | Skill | カテゴリ | LLM | 備考 |
|---|-------|---------|-----|------|
| 1 | `browse_source` | perception | qwen3.5-4b（関連性判定） | 共通基盤 + config/sources/*.yaml |
| 2 | `fetch_rss` | perception | 不要 | ブラウザ不要 |
| 3 | `store_episodic` | memory | 不要 | 行動ログ保存 |
| 4 | `store_semantic` | memory | qwen3.5-4b | 知識抽出・保存 |
| 5 | `recall_related` | memory | 不要 | ベクトル検索 |
| 6 | `llm_call` | reasoning | — | Ollama/MLX統一インターフェース |
| 7 | `parse_llm_output` | reasoning | 不要 | JSONパーサー（2段階） |
| 8 | `resolve_prompt` | reasoning | 不要 | テンプレート解決 |
| 9 | `human_behavior` | browser | 不要 | 操作の人間化 |
| 10 | `verify_x_session` | browser | 不要 | Xセッション確認 |

---

## 3. Phase 1 Skill 詳細 YAML（10 Skill）

Phase 1 で実装する全 Skill の詳細定義。

### 3.1 Perception Skills

#### browse_source

```yaml
name: browse_source
category: perception
version: "1.0.0"
description: "config/sources/*.yamlで定義された情報源から記事・情報を収集する統合Skill"
when_to_use: "定期巡回、またはスケジューラからの呼び出し時"
when_not_to_use: "RSSフィードの取得時（fetch_rssを使う）"

input:
  required:
    source_name:
      type: str
      description: "config/sources/ 内のアダプタ名（例: 'hacker_news', 'yahoo_news', 'x_timeline'）"
  optional:
    topic_filter:
      type: str
      default: ""
      description: "収集結果をフィルタリングするトピック（LLMで関連性判定）"
    max_items:
      type: int
      default: 20
      description: "最大収集件数"

output:
  fields:
    items:
      type: "list[dict]"
      description: "収集した記事/投稿リスト {title, url, content, source, collected_at}"
    source_name:
      type: str
      description: "使用したソースアダプタ名"
    item_count:
      type: int
      description: "収集件数"

execution:
  timeout_sec: 120
  max_retries: 2
  retry_delay_sec: 10
  requires: []  # アダプタの type に応じて動的に決定（browser / api / rss）
  model: qwen3.5-4b  # 関連性判定に使用（topic_filter指定時のみ）
  async: false

rate_limit:
  max_per_hour: null  # アダプタ側の rate_limit に従う
  max_per_day: null
  min_interval_sec: null
  cool_down_on_failure_sec: 120

risk_level: low  # アダプタの risk_level を継承
on_failure: retry
priority: 70
phase: 1
tags: [perception, information_gathering, adapter_pattern]
depends_on: []
```

#### browse_x_timeline

> **アダプタ化（D3）**: この Skill は独立 Skill から `browse_source` のソースアダプタ（config/sources/*.yaml）に移行。以下の定義はアダプタ設定の参考として残す。

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
  model: qwen3.5-4b
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

> **アダプタ化（D3）**: この Skill は独立 Skill から `browse_source` のソースアダプタ（config/sources/*.yaml）に移行。以下の定義はアダプタ設定の参考として残す。

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
  model: qwen3.5-4b
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

> **アダプタ化（D3）**: この Skill は独立 Skill から `browse_source` のソースアダプタ（config/sources/*.yaml）に移行。以下の定義はアダプタ設定の参考として残す。

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

> **アダプタ化（D3）**: この Skill は独立 Skill から `browse_source` のソースアダプタ（config/sources/*.yaml）に移行。以下の定義はアダプタ設定の参考として残す。

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
  model: qwen3.5-4b
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

> **アダプタ化（D3）**: この Skill は独立 Skill から `browse_source` のソースアダプタ（config/sources/*.yaml）に移行。以下の定義はアダプタ設定の参考として残す。

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

> **アダプタ化（D3）**: この Skill は独立 Skill から `browse_source` のソースアダプタ（config/sources/*.yaml）に移行。以下の定義はアダプタ設定の参考として残す。

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

> **ユーティリティ化（D3）**: この操作は独立 Skill から `browse_source` 内部のユーティリティ関数に移行。Skill としては非公開（LLM の選択候補に含まれない）。

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

> **ユーティリティ化（D3）**: この操作は独立 Skill から `browse_source` 内部のユーティリティ関数に移行。Skill としては非公開（LLM の選択候補に含まれない）。

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

> **ユーティリティ化（D3）**: この操作は独立 Skill から `browse_source` 内部のユーティリティ関数に移行。Skill としては非公開（LLM の選択候補に含まれない）。

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
  model: qwen3.5-4b
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
      default: ["episodic", "semantic"]
      description: "検索対象のコレクション（Phase 1: episodic/semantic の 2 コレクションのみ）"
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
  model: qwen3.5-35b-a3b
  async: false

risk_level: none
on_failure: retry
priority: 100
phase: 2
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
  model: qwen3.5-35b-a3b
  async: false

risk_level: none
on_failure: retry
priority: 95
phase: 2
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
# （2_x_browser_strategy.md Section 4 参照）
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

### 3.6 ソースアダプタ YAML の例

`browse_source` が参照する `config/sources/*.yaml` の定義例。

```yaml
# config/sources/hacker_news.yaml
name: hacker_news
type: api
url: "https://hacker-news.firebaseio.com/v0/"
stealth_required: false
always_active: true

extraction:
  method: api_json
  endpoints:
    top: "/topstories.json"
    new: "/newstories.json"
  item_endpoint: "/item/{id}.json"
  fields:
    title: "title"
    url: "url"
    score: "score"
    author: "by"
    comment_count: "descendants"

rate_limit:
  max_per_hour: 4
  min_interval_sec: 600
```

```yaml
# config/sources/yahoo_news.yaml
name: yahoo_news
type: browser
url: "https://news.yahoo.co.jp"
stealth_required: false
always_active: true

extraction:
  method: dom_parse
  selectors:
    article_container: ".newsFeed_item"
    title: ".newsFeed_item_title"
    url: "a[href]"
    summary: ".newsFeed_item_sub"
  wait_for: "domcontentloaded"

rate_limit:
  max_per_hour: 2
  min_interval_sec: 1800
```

---

## 4. Phase 2 Skill 概要定義（11 Skill）

Phase 2 の Skill は概要レベルで定義。Phase 1 完了後に詳細化する。

> **D4**: `select_skill`・`build_llm_context`・`plan_task` は Phase 2 に移動。Phase 1 のSkill選択はルールベーススケジューラが担当する。

| Skill 名 | 概要 | model | 主な input | 主な output |
|-----------|------|-------|-----------|------------|
| `browse_x_profile` | 特定ユーザーのプロフィール・投稿を収集 | qwen3.5-4b | username | profile, posts |
| `browse_tech_feed` | 技術ブログ群の巡回 | qwen3.5-4b | site_list | articles |
| `monitor_diff` | ページの前回スナップショットとの差分検知 | qwen3.5-4b | url | diff_summary, changed |
| `fill_form` | フォーム入力（検索ボックス等） | — | selectors, values | success |
| `store_procedural` | 成功した Skill 実行シーケンスをパターンとして保存 | qwen3.5-4b | skill_sequence, success_rate | stored |
| `compress_memory` | 古い記憶の要約・統合 | qwen3.5-14b | collection, older_than_days | compressed_count |
| `forget_low_value` | importance_score が低い記憶の削除 | — | threshold, collection | deleted_count |
| `reflect` | 直近の行動を振り返り、改善点を抽出 | qwen3.5-14b | recent_actions | insights, adjustments |
| `evaluate_importance` | 情報の重要度をスコアリング | qwen3.5-4b | content, context | importance_score |
| `send_discord` | Discord チャンネルにメッセージ送信 | qwen3.5-14b | channel_id, message | sent |
| `build_persona_context` | キャラクタープロファイルからプロンプト用コンテキストを構築 | — | character_yaml | persona_context |
| `generate_response` | キャラクター性のある応答を生成 | qwen3.5-14b | query, persona_context, memories | response |
| `select_skill` | 現在の状況を分析し、次に実行すべきSkillを選択する（**Phase 2移動 D4**） | qwen3.5-35b-a3b | current_state, available_skills | selected_skill, parameters |
| `build_llm_context` | LLM 呼び出し用のコンテキストを構築する（**Phase 2移動 D4**） | — | memories, persona, task | context |
| `plan_task` | 高レベルの目標を具体的なSkill実行シーケンスに分解する（**Phase 2移動 D4**） | qwen3.5-35b-a3b | goal, constraints | plan |

---

## 5. Phase 3 Skill 概要定義（6 Skill）

| Skill 名 | 概要 | model | 備考 |
|-----------|------|-------|------|
| `post_x` | X に投稿する | qwen3.5-14b | Bot ラベル付きアカウント推奨。Phase 0 の X 判定結果に依存 |
| `reply_x` | X の投稿にリプライする | qwen3.5-14b | 同上 |
| `generate_goal` | 自律的に新しい目標を生成する | qwen3.5-35b-a3b | Procedural Memory を参照して効果的な目標を立てる |
| `update_emotion` | キャラクターの感情状態を更新する | qwen3.5-4b | 行動結果に基づいて遷移 |
| `maintain_presence` | X/Discord での存在感を維持する行動を生成 | qwen3.5-4b | presence.yaml に基づく |

---

## 6. Skill 間の依存関係

### 6.1 暗黙的依存（自動チェーン）

以下の依存は Skill Engine が自動的に処理する。

```
# Phase 1（ルールベーススケジューラ）
Scheduler → browse_source(adapter_name) → [verify_x_session if stealth] → [human_behavior if browser] → 実行
全Skill実行後 → [store_episodic]（自動記録）

# Phase 2+（LLM駆動）
X関連アダプタ → [verify_x_session] → [human_behavior] → browse_source 実行
全Skill実行後 → [store_episodic]（自動記録）
```

### 6.2 推奨チェーン（select_skill が学習する）

```
Phase 1 情報収集:
  Scheduler → browse_source(adapter) → store_semantic

Phase 2+ 情報収集:
  select_skill → recall_related → browse_source(adapter) → store_semantic → reflect

Phase 2+ 質問応答:
  recall_related → build_persona_context → generate_response → send_discord
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
config/
├── skills/                    # Skill定義
│   ├── perception/
│   │   └── browse_source.yaml  # 統合Skill（旧 browse_*）
│   ├── perception/
│   │   └── fetch_rss.yaml
│   ├── memory/
│   │   ├── store_episodic.yaml
│   │   ├── store_semantic.yaml
│   │   ├── recall_related.yaml
│   │   ├── store_procedural.yaml   # Phase 2
│   │   ├── compress_memory.yaml    # Phase 3
│   │   └── forget_low_value.yaml   # Phase 3
│   ├── reasoning/
│   │   ├── llm_call.yaml
│   │   ├── parse_llm_output.yaml
│   │   ├── resolve_prompt.yaml
│   │   ├── select_skill.yaml       # Phase 2
│   │   ├── build_llm_context.yaml  # Phase 2
│   │   ├── plan_task.yaml          # Phase 2
│   │   ├── reflect.yaml            # Phase 2
│   │   ├── evaluate_importance.yaml # Phase 2
│   │   └── generate_goal.yaml      # Phase 3
│   ├── character/                   # Phase 2-3
│   └── browser/
│       ├── human_behavior.yaml
│       └── verify_x_session.yaml
├── sources/                   # ソースアダプタ定義（NEW）
│   ├── hacker_news.yaml
│   ├── github_trending.yaml
│   ├── yahoo_news.yaml
│   ├── google_news.yaml
│   ├── newspicks.yaml
│   ├── rss_feeds.yaml
│   ├── x_timeline.yaml       # Phase 0 Go判定後に有効化
│   └── x_search.yaml
└── schedules/
    └── patrol.yaml            # ルールベース巡回スケジュール
```

命名規則:
- ファイル名 = Skill の `name` フィールドと一致（snake_case）
- カテゴリごとにサブディレクトリで分類
- 1ファイル = 1 Skill（例外なし）
- ソースアダプタは `config/sources/` に配置（Skill 数に影響しない）

---

## 8. Skill 総数

| 追加元 | Phase 1 | Phase 2 追加 | Phase 3 追加 | 累計 |
|--------|---------|-------------|-------------|------|
| 本ドキュメント | 10 | +8 | +10 | **28** |

旧: 38 Skill → 新: **28 Skill**（アダプタパターンによる統合で 10 Skill 削減）
ソースの追加は config/sources/*.yaml で対応（Skill 数に影響しない）



