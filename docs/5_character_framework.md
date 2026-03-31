# Part 5: キャラクターフレームワーク 詳細設計

> **改訂**: 設計レビュー（6_decisions.md D9）に基づき、段階的導入方針を採用。Phase 1 は L1（Big Five 静的値）+ L6（base スタイル）のみ。動的層（L2-L5）は Phase 2-3 で段階的に追加。Big Five ドリフトは Phase 4。

---

## デュアルキャラクター設計

Agentarium は 2 つのキャラクターが常に対話しながら情報を処理する設計（系譜: Zethi / Prako Discord Agent）。

| キャラ | ファイル | 役割 | 特性 |
|--------|---------|------|------|
| **Zephyr**（ゼファー） | `config/characters/zephyr.yaml` | 探索・発見報告役 | 好奇心旺盛、高 openness (0.85)、発見をすぐ共有したがる |
| **Lynx**（リンクス） | `config/characters/lynx.yaml` | 分析・懐疑的検証役 | 論理的・簡潔、高 conscientiousness (0.90)、根拠を必ず問う |

### 対話フロー（概念）

```
[情報収集]
    │
    ▼
Zephyr: 「この記事、すごく重要そうだ。LLM の新しい手法について書いてある」
    │
    ▼
Lynx:   「ソースは？査読済みか？既存手法との差は定量的に示されているか？」
    │
    ▼
Zephyr: 「arXiv のプレプリント。ベンチマーク比較が Section 4 にある」
    │
    ▼
Lynx:   「再現性の記述はあるか？あるなら保存価値あり。なければ保留」
    │
    ▼
[store_semantic / 棄却 の判断]
```

### フェーズ別実装計画

| Phase | 実装内容 |
|-------|---------|
| **1** | 両キャラの L1+L6 を静的値で定義。対話は未実装（単一視点で出力） |
| **2** | `character_dialogue` Skill 追加。2 キャラがプロンプト内で 1 往復対話して出力を決定 |
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
- `config/characters/agent_character.yaml` に L1 の `big_five` + `core_values` + L6 の `base` スタイルのみ定義
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
| Big Five スコアが応答スタイルに反映されるか | プロンプト注入テスト | **2**（Phase 1 は静的値のみで検証対象外） |
| L3 感情が Skill 選択に実際に影響するか | select_skill 出力ログ分析（感情あり/なし比較） | **3** |
| L4 疲労が自然な活動リズムを生むか | 24h 稼働ログ時系列分析 | **3** |
| 性格ドリフトが一貫性を損なわないか | 1 週間稼働後の比較 | **4** |
| 6 層で不足を感じたらどこを分離するか | 運用中のボトルネック分析 | 4+ |

**分離の判断基準**: 「1 つのレイヤー内で変化速度が明らかに異なる 2 つの概念がぶつかる」場合に分離を検討する。
