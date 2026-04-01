# Part 5: キャラクターフレームワーク 詳細設計

> **改訂**: 設計レビュー（6_decisions.md D9）に基づき、段階的導入方針を採用。Phase 1 は L1（Big Five 静的値）+ L6（base スタイル）のみ。動的層（L2-L5）は Phase 2-3 で段階的に追加。Big Five ドリフトは Phase 4。

---

## デュアルキャラクター設計

Agentarium は 2 つのキャラクターが常に対話しながら情報を処理する設計（系譜: Zethi / Prako Discord Agent）。

| キャラ | ファイル | 役割 | 特性 |
|--------|---------|------|------|
| **Zephyr**（ゼファー） | `config/characters/zephyr.yaml` | 探索・発見報告役 | 好奇心旺盛、高 openness (0.85)、発見をすぐ共有したがる |
| **Lynx**（リンクス） | `config/characters/lynx.yaml` | 分析・懐疑的検証役 | 論理的・簡潔、高 conscientiousness (0.90)、根拠を必ず問う |

### 対話フロー（実装）

各キャラクターは独立した LLM 呼び出しを **3〜4 回**行い、合計 **8 回以上/対話セッション** の LLM 呼び出しが発生する。

```
[情報収集]
    │
    ▼
Zephyr（3〜4 llm_call）
  ├─ Step 1: 記事を読んで第一印象を形成
  ├─ Step 2: 重要性・関連性を自己評価
  ├─ Step 3: Lynx への報告内容を整理
  └─ Step 4: （必要に応じて）追加調査クエリを生成
    │
    ▼ Zephyr の報告を Lynx に渡す
    │
Lynx（3〜4 llm_call）
  ├─ Step 1: Zephyr の報告を受けてソース・根拠を評価
  ├─ Step 2: 反論または補足すべき問いを生成
  ├─ Step 3: 保存価値・重要度を判定
  └─ Step 4: 最終判断（store_semantic / 棄却 / 保留）を下す
    │
    ▼
[store_semantic / 棄却 の判断]
```

**LLM 呼び出し数の見積もり（1 情報処理サイクル）**

| フェーズ | 呼び出し数 |
|---------|----------|
| filter_relevance（情報収集後） | 1〜3 回（記事数による） |
| extract_knowledge | 1〜3 回 |
| Zephyr 対話ステップ | 3〜4 回 |
| Lynx 対話ステップ | 3〜4 回 |
| **合計（1サイクル）** | **8〜14 回** |

### フェーズ別実装計画

| Phase | 実装内容 |
|-------|---------|
| **1** | 両キャラの L1+L6 を静的値で定義。対話は未実装（単一視点で出力） |
| **2** | `character_dialogue` Skill 追加。各キャラが独立した LLM スクリプトで 3〜4 ステップ推論し対話 |
| **3** | 感情・疲労状態を反映した動的対話。プラットフォーム別スタイル適応 |
| **4** | Big Five ドリフト。対話の蓄積から関係性・信頼度が変化 |

---

## 段階的導入計画

| レイヤー | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|---------|---------|---------|---------|---------|
| L1 Core Identity | **静的値のみ** | ✅ | ✅ | ドリフト有効化 |
| L2 Motivation | — | **静的 goals** | 動的 goals | ✅ |
| L3 Emotional State | — | — | **ルールベース** | ✅ |
| L4 Cognitive State | — | — | **疲労モデル** | ✅ |
| L5 Relationship & Trust | — | — | **source_trust** | ✅ |
| L6 Communication Style | **base のみ** | platform 適応 | emotion 修飾 | ✅ |

Phase 1 で実装するもの:
- `config/characters/zephyr.yaml` / `lynx.yaml` に L1 の `big_five` + `core_values` + L6 の `base` スタイルのみ定義
- キャラクター系 Skill（build_persona_context 等）は Phase 2 から
- 感情 / 疲労 / ドリフトは全て Phase 3-4

---

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
  # LLM system prompt に含めるキャラクター性格の prose 記述（D17）
  # Big Five 数値は機械処理用、prose は LLM への自然言語説明用として併用
  personality_prose: ""
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

#### 感情軸 マスターリスト（20軸）

全 20 軸が存在しうる感情の語彙。LLM には毎回全軸を問わず、**キャラクター別の `active_axes` に含まれる軸のみ**出力を要求する（D15）。

| カテゴリ | 軸 |
|---------|-----|
| 基本感情（Plutchik 8基本） | `joy` `sadness` `fear` `anger` `surprise` `anticipation` `trust` `disgust` |
| 強度バリアント | `excitement` `anxiety` `frustration` `boredom` |
| 認知 | `curiosity` `awe` `confusion` |
| 社会 | `pride` `shame` |
| エージェント固有 | `satisfaction` `restlessness` `relief` |

#### キャラクター別 active_axes

LLM の affect_mapping プロンプトでは **active_axes の軸のみ**を出力要求する。
キャラクター YAML の `emotional_axes.active` で定義。

| キャラ | active_axes | 傾向 |
|--------|------------|------|
| Zephyr | curiosity, excitement, anticipation, boredom, awe, joy, satisfaction, restlessness, anxiety, pride | 探索・発見系（10軸） |
| Lynx | satisfaction, frustration, curiosity, trust, confusion, anticipation, pride, disgust, relief | 検証・達成系（9軸） |

#### 感情状態の永続化（D18）

- **WorkingMemory（インメモリ）**: 実行中の高速アクセス
- **`data/state/emotional_state_{character}.json`**: 起動時読み込み・更新時即時書き込み
- Qdrant には保存しない（現在値1点の保存にベクトルDBは過剰）

```json
// data/state/emotional_state_zephyr.json の例
{
  "character": "zephyr",
  "updated_at": "2026-04-01T17:00:00Z",
  "state": {
    "curiosity": 0.65,
    "excitement": 0.50,
    "anticipation": 0.60,
    "boredom": 0.30,
    "awe": 0.50,
    "joy": 0.50,
    "satisfaction": 0.50,
    "restlessness": 0.50,
    "anxiety": 0.20,
    "pride": 0.50
  }
}
```

#### 感情の更新と減衰

- **affect_mapping（コンテンツ受信時）**: LLM が active_axes の delta を JSON 出力（バッチ処理, D19）
- **Skill 実行トリガー**: AgentLoop が rule-based で固定 delta を適用
- **減衰**: 1時間ごとに中立点（0.5）方向に 0.1 ずつ戻る

```yaml
# Skill実行トリガー（ルールベース。LLMは使わない）
skill_triggers:
  on_skill_success:   { satisfaction: +0.1, frustration: -0.05, pride: +0.05 }
  on_skill_failure:   { frustration: +0.15, satisfaction: -0.05, anxiety: +0.05 }
  on_user_interaction: { satisfaction: +0.1, boredom: -0.1 }
decay:
  rate_per_hour: 0.1
  neutral_point: 0.5
```

#### Skill 選択への影響

```yaml
skill_influence:
  high_curiosity:
    boost_skills: [browse_source, browse_hacker_news, browse_github_trending]
    boost_amount: 0.2
  high_frustration:
    avoid_skills: [browse_x_timeline, browse_x_search]
    prefer_skills: [fetch_rss, recall_related]
  high_boredom:
    boost_skills: [browse_source, browse_github_trending]
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

## 5. build_persona_context — コンテキストプロファイル方式（D20）

Layer 番号（L2, L3 等）でのフィールド指定を廃止し、用途別の名前付きプロファイルに置き換える。

```python
# 呼び出し方
context = build_persona_context(character="zephyr", profile="filter_relevance")
```

プロファイルは `config/characters/context_profiles.yaml` で定義する。

| プロファイル名 | 呼び出し元 Skill | 含むフィールド | 理由 |
|--------------|----------------|--------------|------|
| `filter_relevance` | `filter_relevance` | interests, active_emotional_axes[curiosity, boredom] | キャラの関心と飽き具合で関連度判定 |
| `generate_response` | `generate_response` | big_five, personality_prose, communication_style, source_trust, emotional_state(active_axes) | キャラクターの「声」に全情報が必要 |
| `reflect` | `reflect` | self_knowledge, emotional_state[curiosity, satisfaction, frustration] | 自己認識と感情が振り返りの質に影響 |
| `store_semantic` | `store_semantic` | interests.primary, self_knowledge.confident_domains | 何を重要と判断するかに影響 |
| `affect_mapping` | `update_emotional_state` | big_five, personality_prose, emotional_axes.active, emotional_state_defaults | 感情 delta 算出のためのキャラ定義 |

---

## 6. 検証計画

| 検証項目 | 方法 | Phase |
|---------|------|-------|
| Big Five スコアが応答スタイルに反映されるか | プロンプト注入テスト | **2**（Phase 1 は静的値のみで検証対象外） |
| L3 感情が Skill 選択に実際に影響するか | select_skill 出力ログ分析（感情あり/なし比較） | **3** |
| L4 疲労が自然な活動リズムを生むか | 24h 稼働ログ時系列分析 | **3** |
| 性格ドリフトが一貫性を損なわないか | 1 週間稼働後の比較 | **4** |
| 6 層で不足を感じたらどこを分離するか | 運用中のボトルネック分析 | 4+ |

**分離の判断基準**: 「1 つのレイヤー内で変化速度が明らかに異なる 2 つの概念がぶつかる」場合に分離を検討する。

---

## 7. L3 更新トリガー — コンテンツ処理パイプラインとの接続

> 詳細設計: [9_content_processing_pipeline.md](9_content_processing_pipeline.md)

L3 の更新は「Skill 成功/失敗」だけでなく、**コンテンツ受信時の感情マッピング**でも発生する。

### 更新トリガー一覧

| トリガー | 発生タイミング | 実装 Skill |
|---------|--------------|-----------|
| `on_skill_success` | Skill 実行成功時 | AgentLoop（既存） |
| `on_skill_failure` | Skill 実行失敗時 | AgentLoop（既存） |
| `on_content_received` | **コンテンツ処理パイプライン ④ affect_mapping** | `update_emotional_state`（Phase 2 新設） |
| `on_user_interaction` | Discord/X でメッセージ受信時 | `update_emotional_state`（Phase 2） |

### affect_mapping の処理フロー

```
新規コンテンツ取得（タイトル + 要約）
    ↓
update_emotional_state Skill
    │
    ├─ input:  summary, topics, character_name, current_L3
    ├─ LLM:   "{character_name} がこの情報を受け取ったとき感情はどう変化するか？"
    │          （L1 Big Five を system prompt に含める）
    └─ output: { emotional_delta: { curiosity: +0.2, excitement: +0.1, ... } }
         ↓
L3 Emotional State 更新（WorkingMemory）
         ↓
┌─────────────────────────────────────┐
│ 更新された L3 が以下に影響            │
│  ・select_skill の判断軸             │
│  ・generate_response のトーン        │
│  ・synthesize_speech の声質 (Phase 4)│
│  ・update_avatar_expression (Phase 4)│
└─────────────────────────────────────┘
```

### キャラクター別の感情傾向（L1 Big Five との対応）

**Zephyr（openness: 0.85, extraversion: 0.75）**

| コンテンツタイプ | 感情変化 |
|---------------|---------|
| AI/OSS の新発見 | curiosity ↑↑, excitement ↑ |
| 既知情報の繰り返し | boredom ↑ |
| SNS/コミュニティの炎上 | anxiety わずかに↑ |
| 自分の関心ドメイン外 | 変化なし（フィルタ棄却） |

**Lynx（conscientiousness: 0.90, neuroticism: 0.30）**

| コンテンツタイプ | 感情変化 |
|---------------|---------|
| 実測データ・論文付き記事 | satisfaction ↑ |
| 根拠不明の主張 | frustration ↑ |
| 複数ソースで確認できた事実 | satisfaction ↑, curiosity わずかに↑ |
| 矛盾する情報（contradicts 関係） | curiosity ↑（調査したくなる） |

---

## 8. マルチモーダル出力 — TTS・VTubeStudio との連携

L3 Emotional State は**テキスト出力だけでなく、音声・アバター表情にも直結する**設計。

### 出力モダリティ一覧

```
L3 Emotional State
  { curiosity: 0.8, excitement: 0.6, frustration: 0.0 }
        │
        ├─── テキスト ────────► generate_response Skill
        │                        L6 Communication Style で修飾
        │                        → Discord / X 投稿
        │
        ├─── 音声 ────────────► synthesize_speech Skill       (Phase 4)
        │                        感情値 → 声質パラメータにマッピング
        │                        → VOICEVOX / Style-Bert-VITS2
        │
        └─── アバター表情 ────► update_avatar_expression Skill (Phase 4)
                                 感情値 → VTubeStudio パラメータ注入
                                 → WebSocket API
```

### 実装方針

**アーキテクチャへの影響はゼロ**。Skill 追加 + character YAML への `expression_mapping` セクション追加のみ。

```yaml
# config/characters/zephyr.yaml（Phase 4 拡張部分）
expression_mapping:
  # L3 感情値 → VTubeStudio パラメータ名 + 強度係数
  vtubestudio:
    curiosity:
      param: "BrowRaise"
      scale: 0.5          # curiosity: 0.8 → BrowRaise: 0.4
    excitement:
      param: "MouthSmile"
      scale: 0.8
    frustration:
      param: "BrowFurrow"
      scale: 0.7
    satisfaction:
      param: "EyeSmile"
      scale: 0.6

  # L3 感情値 → TTS 音声パラメータ
  tts:
    engine: "style_bert_vits2"   # または "voicevox"
    speaker_id: 0
    emotion_params:
      excitement: { speed: 1.15, pitch: +0.1 }
      frustration: { speed: 0.95, pitch: -0.05 }
      boredom:     { speed: 0.90, energy: -0.2 }
```

### Skill 実装計画

| Skill | ファイル | Phase | API |
|-------|---------|-------|-----|
| `synthesize_speech` | `skills/action/synthesize_speech.py` | **4** | VOICEVOX REST / Style-Bert-VITS2 REST |
| `update_avatar_expression` | `skills/action/update_avatar_expression.py` | **4** | VTubeStudio WebSocket |
| `play_audio` | `skills/action/play_audio.py` | **4** | ローカル再生 or VC 配信 |

### Style-Bert-VITS2 を推奨する理由

VOICEVOX（Phase 4 に既記載）との比較：

| 比較軸 | VOICEVOX | Style-Bert-VITS2 |
|--------|---------|-----------------|
| 感情パラメータ | なし | joy / sad / anger / surprise を直接指定可能 |
| L3 との対応 | 手動マッピング必要 | L3 感情軸と自然に対応 |
| API | REST（シンプル） | REST（シンプル） |
| 音質 | 高品質 | 高品質 |
| ローカル実行 | ✅ | ✅ |
| **推奨** | Phase 4 初期検証用 | **Phase 4 本採用候補** |
