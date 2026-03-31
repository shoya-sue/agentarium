# Part 4: LLM プロンプト / コンテキスト管理 詳細設計

> **改訂**: 設計レビュー（6_decisions.md D1/D5/D6/D10）に基づき、LLM モデルを Qwen3.5-35B-A3B に更新、コンテキスト長を 16384+ に拡張、圧縮戦略を 2 段階に簡素化、埋め込みモデルを Phase 0 で検証。

---

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

Qwen3.5-35B-A3B のコンテキスト長は 262K だが、VRAM 効率のため `OLLAMA_NUM_CTX=16384` で運用する。

```
トークン配分（16384 tokens 上限の場合）:

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
[llm_call（messages, model="qwen3.5-35b-a3b"）]
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
- Qwen3.5-35B-A3B は MoE アーキテクチャで活性パラメータ 3B

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
この判定には軽量モデル（qwen3.5-4b）を使う。

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
  qwen3.5-35b-a3b:
    max_context: 16384
    reserved_for_output: 4000
    available_for_input: 12384
    sections:
      system_prompt: { max: 1500, priority: 1, compress: false }
      current_state: { max: 400, priority: 2, compress: false }
      recalled_memories: { max: 1500, priority: 3, compress: true }
      available_skills: { max: 2000, priority: 4, compress: true }
      persona: { max: 500, priority: 5, compress: true }
      extra: { max: 292, priority: 6, compress: true }

  qwen3.5-14b:
    max_context: 16384
    reserved_for_output: 2000
    available_for_input: 6192
    # 同様の配分

  qwen3.5-4b:
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
    select_skill: qwen3.5-35b-a3b
    plan_task: qwen3.5-35b-a3b
    generate_goal: qwen3.5-35b-a3b
    reflect: qwen3.5-14b
    generate_response: qwen3.5-14b
    send_discord: qwen3.5-14b
    compress_memory: qwen3.5-14b

  # --- カテゴリベースのフォールバック ---
  category_default:
    reasoning: qwen3.5-35b-a3b
    character: qwen3.5-14b
    perception: qwen3.5-4b        # 関連性判定等の軽量タスク
    memory: qwen3.5-4b            # 知識抽出等
    action: null                # action Skill は基本的に LLM 不要
    browser: null

  # --- 最終フォールバック ---
  default: qwen3.5-4b

# --- 埋め込み用（記憶の保存・検索）---
embedding_model: 埋め込みモデル（Phase 0 で選定: nomic-embed-text or multilingual-e5-base）
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

`build_persona_context` が参照するキャラクター構造は 6 層モデル（5_character_framework.md 参照）。
Skill ごとに含めるレイヤーを動的に調整する設計は `5_character_framework.md-character-framework.md` Section 5 に定義。

