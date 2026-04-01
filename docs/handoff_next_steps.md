# 引き継ぎ: キャラクターフレームワーク再設計 完了後の次ステップ

**作成日**: 2026-04-01
**引き継ぎ先**: 新しい Claude Code セッション
**コンテキスト**: D15-D20（キャラクターフレームワーク再設計）が設計として完了。次は実装への反映。

---

## 完了した設計変更（このセッション）

コミット `80893d9` — `design: キャラクターフレームワーク再設計（D15-D20）`

| 決定 | 内容 |
|------|------|
| D15 | 感情軸: 20軸マスター + キャラ別 active_axes（Zephyr 10軸 / Lynx 9軸） |
| D16 | 感情初期化: Big Five 静的デフォルト値を YAML に定義 |
| D17 | L1 に `personality_prose` 追加（Big Five 数値と併用） |
| D18 | 感情永続化: WorkingMemory + JSON ファイル（Qdrant不使用） |
| D19 | affect_mapping: バッチ化 + Qwen3.5-4B |
| D20 | build_persona_context: Layer 廃止 → context_profiles.yaml プロファイル方式 |

変更ファイル:
- `docs/5_character_framework.md` — L3 設計更新、コンテキストプロファイル方式記述
- `docs/6_decisions.md` — D15-D20 詳細追記
- `config/characters/zephyr.yaml` — personality_prose / emotional_axes.active / emotional_state_defaults 追加
- `config/characters/lynx.yaml` — 同上
- `config/characters/context_profiles.yaml` — 新規作成（5プロファイル定義）

---

## 設計と実装のギャップ（次セッションで対応すべき箇所）

### 1. `build_persona_context.py` の更新（最優先）

**現状**: `profile` パラメータなし。全データを固定形式で出力。`behavioral_descriptors` を LLM に渡している。

**必要な変更**:
- `profile` パラメータを追加（`filter_relevance` / `generate_response` / `reflect` / `store_semantic` / `affect_mapping`）
- `context_profiles.yaml` を読み込み、プロファイルに応じてフィールドを選択
- `personality_prose` を読んで LLM プロンプトに含める（`behavioral_descriptors` の代わり）
- `emotional_state` の現在値（JSON から読み込み済み前提）を active_axes 分だけ含める

ファイル: `agent-core/src/skills/character/build_persona_context.py`

### 2. `update_emotional_state` Skill の新規実装（Phase 2）

**現状**: ファイルなし（設計のみ）

**必要な実装**:
- ファイル: `agent-core/src/skills/character/update_emotional_state.py`
- Skill 定義: `config/skills/character/update_emotional_state.yaml`
- 処理:
  1. `data/state/emotional_state_{character}.json` を読み込む
  2. filter_relevance 通過コンテンツをバッチで Qwen3.5-4B に渡す（D19）
  3. active_axes の emotional_delta を JSON 配列で受け取る
  4. 各軸に delta を加算（clamp: 0.0〜1.0）
  5. `data/state/emotional_state_{character}.json` に書き込む
- LLM プロンプトは `config/prompts/user/affect_mapping.yaml` に切り出す

**バッチ入力フォーマット**:
```json
{
  "character": "zephyr",
  "personality_prose": "...",
  "big_five": {...},
  "active_axes": ["curiosity", "excitement", ...],
  "current_state": {"curiosity": 0.65, ...},
  "contents": [
    {"index": 0, "summary": "...", "topics": ["LLM", "OSS"]},
    {"index": 1, "summary": "...", "topics": ["Python"]}
  ]
}
```

**期待出力フォーマット**:
```json
[
  {"index": 0, "emotional_delta": {"curiosity": 0.2, "excitement": 0.3}},
  {"index": 1, "emotional_delta": {"curiosity": 0.1, "boredom": -0.1}}
]
```

### 3. 感情状態の初期化処理（Phase 2）

**現状**: `data/state/` ディレクトリなし。起動時に感情状態を読み込む処理もなし。

**必要な実装**:
- `agent-core/src/core/working_memory.py` に感情状態の load/save メソッド追加
- 起動時に `data/state/emotional_state_{character}.json` が存在しなければ `emotional_state_defaults` から初期ファイルを生成
- 更新時に即時 JSON 書き込み

### 4. `build_persona_context.py` の `skills/character/` → `character/` YAML 設定ファイルとの整合

現在の Skill 定義 YAML が存在するか確認が必要:
- `config/skills/character/build_persona_context.yaml`

---

## 実装優先順

| 優先度 | タスク | Phase | 状態 |
|--------|------|-------|------|
| 1 | `build_persona_context.py` に `profile` パラメータ追加 + `personality_prose` 対応 | 2 | **完了** |
| 2 | `data/state/` 感情状態 JSON の初期化・load/save 処理 | 2 | **完了** |
| 3 | `update_emotional_state` Skill 新規実装（バッチ affect_mapping） | 2 | **完了** |
| 4 | `context_profiles.yaml` との結合テスト | 2 | **完了** |

---

## 参照ファイル

| ファイル | 内容 |
|---------|------|
| `docs/5_character_framework.md` | L3 設計・コンテキストプロファイル方式・20軸マスターリスト |
| `docs/6_decisions.md` | D15-D20 詳細（キャラクターフレームワーク再設計の意思決定全文） |
| `config/characters/zephyr.yaml` / `lynx.yaml` | personality_prose / emotional_axes.active / emotional_state_defaults |
| `config/characters/context_profiles.yaml` | 5プロファイル定義 |
| `agent-core/src/skills/character/build_persona_context.py` | 現在の実装（更新対象） |
| `docs/9_content_processing_pipeline.md` | affect_mapping のパイプライン全体図 |
