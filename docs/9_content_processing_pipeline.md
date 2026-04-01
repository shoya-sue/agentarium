# Part 9: コンテンツ処理パイプライン設計

> 情報収集後のデータをどう処理・蓄積・活用するかを定義する。
> 「生テキストをそのまま埋め込む」問題を解消し、要約・事実抽出・リレーション・感情マッピングを一気通貫で実施する。

---

## 背景と問題意識

### 現状（Phase 1）の問題

```
取得コンテンツ（生テキスト）
    ↓
embed(raw_text) → Qdrant に保存
```

| 問題 | 影響 |
|------|------|
| 生テキストを埋め込む | ノイズ多・埋め込み品質低（広告文・ナビゲーションテキストが混入） |
| facts フィールドが空 | 記憶が「点」の集合になる。関連付け・推論ができない |
| 感情変化なし | キャラクターが何を見ても同じ判断軸で行動する |
| 重複記事の重複保存 | 類似度チェックなし。同じニュースが複数経路で入ると重複 |

### あるべき姿

取得した情報を「粗い事実の塊」から「構造化された知識ノード」に変換し、
感情・リレーション・重要度を付与した上で保存する。

---

## パイプライン全体図

```
コンテンツ取得
（browse_source / rss / hn_api）
    ↓
┌──────────────────────────────────────────────────┐
│          コンテンツ処理パイプライン                  │
│                                                  │
│  ① filter_relevance                              │
│     LLM: キャラクターの interests と関連するか？   │
│     スコア < 閾値 → 棄却（以降の処理スキップ）      │
│                      ↓                           │
│  ② summarize + extract_knowledge                 │
│     LLM: 要約（100-200文字）                      │
│          トピックタグ（3-5個）                      │
│          事実リスト（"X社がYをリリース" 等）         │
│          重要度スコア（0.0-1.0）                    │
│                      ↓                           │
│  ③ extract_relations                             │
│     recall_related で類似記憶を検索               │
│     LLM: 既存記憶 A との関係を分類                 │
│          （supports / contradicts / extends /    │
│            related / same_topic）                │
│     → related_ids リストを生成                    │
│                      ↓                           │
│  ④ affect_mapping                                │
│     LLM: このコンテンツを受け取ったとき             │
│          {character_name} の感情はどう変化するか？  │
│     → { curiosity: +0.2, excitement: +0.1, ... } │
│     → L3 Emotional State を更新                  │
│                      ↓                           │
│  ⑤ store_semantic                               │
│     embed 対象 = 要約 + トピック（生テキストではなく）│
│     payload に全情報を保存                         │
│                                                  │
└──────────────────────────────────────────────────┘
    ↓
Qdrant semantic コレクション（構造化知識ノード）
    ↓
L3 Emotional State 更新 → select_skill / generate_response に影響
```

---

## 各ステップ詳細

### ① filter_relevance

**目的**: 不要コンテンツを早期棄却してLLMコスト削減

```yaml
# 入力
content:
  title: "..."
  summary_or_snippet: "..."   # 本文全体ではなくスニペット（コスト削減）
  source: "qiita"

character_interests:           # L2 Motivation から参照
  primary: ["AI", "LLM", "OSS", "Web技術"]
  emerging: ["量子コンピュータ", "エッジAI"]

# 出力（JSON）
{
  "relevant": true,
  "relevance_score": 0.82,
  "matched_interests": ["LLM", "OSS"],
  "reason": "Qwen3.5 の新機能に関する記事で primary interests に直結"
}
```

**閾値**: `relevance_score < 0.4` → 棄却（Phase 1 は 0.3 でスタート、運用で調整）

---

### ② summarize + extract_knowledge

**目的**: 生テキストを構造化知識に変換

```yaml
# 入力
content: "（記事本文）"
title: "..."
url: "..."

# 出力（JSON）
{
  "summary": "Anthropicが新しいClaude 3.5 Haikuを発表。前モデル比2倍の処理速度...",
  "topics": ["Claude", "LLM", "Anthropic", "AI性能"],
  "facts": [
    "Claude 3.5 Haiku は前モデル比2倍の処理速度",
    "APIコストは入力$0.80/MTok",
    "コード生成ベンチマークで GPT-4o-mini を上回る"
  ],
  "importance_score": 0.85,
  "content_type": "product_announcement"  // news / tutorial / research / discussion
}
```

**LLMモデル**: Qwen3.5-4B（軽量。要約タスクは小モデルで十分）

---

### ③ extract_relations

**目的**: 孤立した「点」の記憶をつなぐ「グラフエッジ」を作る

```yaml
# 処理フロー
1. recall_related(summary, limit=5) で類似記憶を検索
2. LLM に (新記事要約, 既存記憶要約) ペアを渡して関係分類

# 関係タイプ
supports:      新記事が既存記憶の主張を補強する
contradicts:   新記事が既存記憶と矛盾する
extends:       同じ話題の続報・深掘り
related:       直接ではないが同ドメインで関連
same_topic:    同じ出来事の別ソース報道

# 出力（JSON）
{
  "related_ids": [
    {
      "point_id": "uuid-xxx",
      "relation_type": "extends",
      "strength": 0.75,
      "note": "前回の Haiku 性能評価記事の続報"
    }
  ]
}
```

**注意**: related_ids は Qdrant の payload に保存するだけ。Phase 2 では単方向リンク。
Phase 4 で GraphRAG（Neo4j 等）に移行するか判断する。

---

### ④ affect_mapping

**目的**: コンテンツ受信時の感情インパクトを評価し L3 を更新する

```yaml
# 入力
summary: "Qwen3.5 の新バージョンが発表..."
topics: ["LLM", "OSS"]
character_name: "zephyr"
current_emotional_state:
  curiosity: 0.5
  satisfaction: 0.5
  excitement: 0.2

# 出力（JSON）
{
  "emotional_delta": {
    "curiosity": +0.25,    // AI/LLM 関連で好奇心が刺激された
    "excitement": +0.30,   // 新発表で興奮
    "satisfaction": +0.05
  },
  "affect_reason": "AI モデルの新発表。Zephyr の primary interests に直結する発見"
}
```

**LLMへの指示方針**:
- キャラクター定義（L1 Big Five）を system prompt に含める
- `openness` が高いキャラクターは novel_discovery で curiosity + excitement が大きく上がる
- `neuroticism` が高いキャラクターは不確実なニュースで anxiety が上がる

**Zephyr（openness: 0.85）の傾向**:
- AI/OSS の新発見 → curiosity ↑↑, excitement ↑
- 既知情報の繰り返し → boredom ↑
- X・SNS 関連のネガティブニュース → anxiety わずかに↑

**Lynx（conscientiousness: 0.90）の傾向**:
- 根拠のない主張 → frustration ↑
- 論文・実測データ付きの記事 → satisfaction ↑
- 複数ソースで確認できた事実 → 興奮より満足

---

### ⑤ store_semantic（拡張スキーマ）

現在の store_semantic を拡張する。

```python
# embed 対象（変更）
embed_text = f"{summary}. Topics: {', '.join(topics)}"
# ↑ 生テキストではなく要約 + トピックを埋め込む

# payload（拡張）
payload = {
    "source_url": url,
    "title": title,
    "summary": summary,           # 要約（追加）
    "topics": topics,
    "facts": facts,               # 事実リスト（追加）
    "importance_score": score,
    "content_type": content_type, # 追加
    "related_ids": related_ids,   # リレーション（追加）
    "affect_delta": affect_delta, # 感情インパクト（追加）
    "stored_at": iso_timestamp,
    # 生テキストは保存しない（Qdrant のメモリ節約）
    # 必要なら source_url から再取得
}
```

---

## 重複コンテンツの扱い

同じニュースが複数ソース（HN + RSS + Yahoo News）から入る問題への対策：

```
① store_semantic 前に recall_related(title, limit=1) で類似チェック
② 類似度 > 0.92 かつ source_url ドメインが異なる → 重複とみなす
③ 新規保存せず、既存 point の related_ids に「same_topic」として追記
```

Phase 1 では URLベースの単純重複チェックのみ実施。類似度チェックは Phase 2。

---

## フェーズ別実装計画

| ステップ | Phase 1 | Phase 2 | Phase 3 |
|---------|---------|---------|---------|
| ① filter_relevance | evaluate_importance で代替（スコア閾値のみ） | interests 参照で精度向上 | L2 動的 goals 連動 |
| ② summarize + extract | **実装**（Qwen3.5-4B） | facts 品質向上 | Zephyr/Lynx 対話で評価 |
| ③ extract_relations | **実装**（単方向リンクのみ） | 双方向 + 関係強度の更新 | GraphRAG 移行判断 |
| ④ affect_mapping | **実装**（L3 の最初の動的更新） | キャラクター別チューニング | 感情→Skill選択 連動 |
| ⑤ store_semantic 拡張 | **実装** | 重複チェック追加 | 検索クエリ最適化 |

---

## Skill 実装計画

| Skill | ファイル | Phase | 備考 |
|-------|---------|-------|------|
| `summarize_content` | `skills/reasoning/summarize_content.py` | **2** | ②を担う。Qwen3.5-4B 使用 |
| `extract_relations` | `skills/memory/extract_relations.py` | **2** | ③を担う |
| `update_emotional_state` | `skills/character/update_emotional_state.py` | **2** | ④を担う。L3 更新 |
| `store_semantic` | 既存を拡張 | **2** | ⑤スキーマ拡張 |

既存の `evaluate_importance` は ① の簡易版として Phase 1 で継続使用。

---

## recall_related への影響

処理パイプラインを通すことで `recall_related` の検索品質が大きく向上する。

| 比較軸 | Before（生テキスト） | After（要約+構造化） |
|--------|-------------------|--------------------|
| embed 対象 | 広告・UI テキスト含む | 記事の本質のみ |
| 検索ノイズ | 高い | 低い |
| 関連記事の発見 | ベクトル類似度のみ | ベクトル + related_ids グラフ |
| キャラクター親和性 | なし | affect_delta でフィルタ可能 |

---

## 参照設計書

- [キャラクターフレームワーク](5_character_framework.md) — L3 感情状態の定義と更新ポリシー
- [Skill 定義](3_skill_definition.md) — 各 Skill の入出力スキーマ
- [意思決定ログ](6_decisions.md) — D7（Qdrantコレクション設計）
