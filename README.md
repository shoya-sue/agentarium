# Agentarium — Autonomous Personal Agent

24時間自律動作する AI Agent。X と Discord に常駐し、Web ブラウジング・情報収集・知識蓄積・デュアルキャラクター対話を自律的に行う。

**系譜**: Zethi / Prako Discord Agent → 発展型

---

## 技術スタック

| 要素 | 採用技術 |
|------|---------|
| 言語 | Python 3.12 |
| LLM | Qwen3.5-35B-A3B（Ollama / MLX、ローカル） |
| 埋め込み | nomic-embed-text or multilingual-e5（Phase 0 で選定） |
| ブラウザ | Playwright Stealth（rebrowser-playwright） |
| 記憶 | Qdrant（ベクトルDB） |
| 実行環境 | Docker Compose + ホスト直接 Ollama/MLX（Mac M4 Pro 48GB） |
| 監視 | Dashboard（Node.js） |

---

## アーキテクチャ概要

```
Scheduler（patrol.yaml）
    └─ Skill Engine
         ├─ browse_source ──→ Source Adapters（HN / RSS / Yahoo / GitHub / X ...）
         ├─ fetch_rss
         ├─ store_episodic ──→ Qdrant: episodic
         ├─ store_semantic ──→ Qdrant: semantic
         ├─ recall_related
         ├─ llm_call ────────→ Qwen3.5-35B-A3B（Ollama / MLX）
         └─ ...

Dual Character Dialogue（2キャラクターが情報を議論して出力を生成）
    ├─ Zephyr（好奇心・探索型）
    └─ Lynx（分析・懐疑型）
```

**設計原則**:
- Skill 単一責任 — 各 Skill は 1 つの機能に集中
- アダプタパターン — 情報源は YAML 設定で追加、コード変更不要
- 段階的複雑化 — Phase 1 はルールベース。LLM 駆動は Phase 2+
- INPUT = YAML / OUTPUT = JSON（厳守）

---

## ディレクトリ構成

```
agentarium/
├── config/                    # 全設定（YAML）
│   ├── characters/            # キャラクター定義（zephyr, lynx）
│   ├── schedules/             # 巡回スケジュール
│   ├── sources/               # ソースアダプタ（サイトごとの YAML）
│   ├── llm/                   # LLM ルーティング・コンテキスト設定
│   └── prompts/               # system / user / output_schema
├── agent-core/                # Python Agent 本体
│   └── src/
│       ├── core/              # SkillSpec, SkillEngine, SafetyGuard
│       ├── skills/            # Skill 実装
│       ├── adapters/          # ソースアダプタ実装
│       └── scheduler/
├── browser/                   # Playwright Stealth コンテナ
├── dashboard/                 # 監視 UI
├── data/                      # 全出力（JSON）
└── docs/                      # 設計書（下記参照）
```

---

## 実装フェーズ

| Phase | 目的 | 状態 |
|-------|------|------|
| **0** | 技術検証（LLM 速度・埋め込み日本語・Stealth） | **次に着手** |
| 1 | 情報収集 Agent（アダプタ + ルールベース巡回） | 未着手 |
| 2 | 記憶強化 + キャラクター対話 + Discord + LLM 駆動 Skill 選択 | 未着手 |
| 3 | 完全自律 + 感情・疲労モデル + デュアルプレゼンス | 未着手 |
| 4 | 発展・最適化（GraphRAG, VOICEVOX, ドリフト等） | 未着手 |

---

## 設計書

| # | ファイル | 内容 |
|---|---------|------|
| 0 | [目次](docs/0_index.md) | 設計書一覧 |
| 1 | [計画書本体](docs/1_plan.md) | 概要・アーキテクチャ・フェーズ計画 |
| 2 | [X ブラウザアクセス戦略](docs/2_x_browser_strategy.md) | bot 検出対策・Stealth 構成 |
| 3 | [Skill 定義](docs/3_skill_definition.md) | Skill YAML 定義・アダプタパターン |
| 4 | [LLM プロンプト管理](docs/4_llm_prompt_context.md) | Working Memory・トークン制御 |
| 5 | [キャラクターフレームワーク](docs/5_character_framework.md) | 6 層心理モデル・デュアルキャラクター設計 |
| 6 | [意思決定ログ](docs/6_decisions.md) | D1-D11 設計レビュー結果 |
| 7 | [Phase 0 検証手順書](docs/7_phase0_verification.md) | 具体的な検証コマンドと Go/No-Go 判定 |

---

## クイックスタート

```bash
# Ollama（ホスト直接実行）
ollama pull qwen3.5:35b-a3b
OLLAMA_NUM_CTX=16384 ollama serve

# Docker（Qdrant + ブラウザ）
docker compose up -d

# Agent 起動
cd agent-core && python -m src.main

# テスト
cd agent-core && python -m pytest tests/
```

Phase 0 の具体的な検証手順 → [docs/7_phase0_verification.md](docs/7_phase0_verification.md)
