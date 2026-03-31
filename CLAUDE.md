# Agentarium — Autonomous Personal Agent

## プロジェクト概要

24時間自律動作するAI Agent。X と Discord に常駐し、Web ブラウジング・情報収集・知識蓄積・キャラクター対話を自律的に行う。
Zethi/Prako Discord Agent + Talkov-Chan Skill Architecture の発展型。

## 技術スタック

- **言語**: Python 3.12
- **LLM**: Ollama or MLX（ローカル） — **Qwen3.5-35B-A3B** / Qwen3.5-14B / Qwen3.5-4B
- **埋め込み**: Phase 0 で検証（nomic-embed-text vs multilingual-e5-base）
- **ブラウザ**: Playwright Stealth（rebrowser-playwright）
- **記憶**: Qdrant（ベクトルDB）
- **実行環境**: Docker Compose + ホスト直接 Ollama/MLX（Mac M4 Pro 48GB）
- **監視**: Dashboard（Node.js）

## アーキテクチャ

- **Skill-based Architecture**: 共通基盤 + ソースアダプタパターン
- **ファイル規約**: INPUT = YAML / OUTPUT = JSON（厳守）
- **Skill選択**: Phase 1 ルールベース → Phase 2 LLM駆動
- **記憶**: Working Memory → Qdrant 2コレクション（Phase 1: episodic/semantic）
- **キャラクター**: 6層心理フレームワーク（Phase 1: L1+L6 静的値のみ）

## ディレクトリ構成

```
agentarium/
├── docker-compose.yml
├── .env
├── config/                    # INPUT: 全て YAML
│   ├── settings.yaml
│   ├── safety.yaml / safety_x.yaml
│   ├── llm/routing.yaml
│   ├── llm/context_limits.yaml
│   ├── sources/               # ソースアダプタ設定（サイトごとのYAML）
│   ├── skills/                # Skill定義（1ファイル=1Skill）
│   ├── characters/            # キャラクター定義
│   ├── schedules/             # 巡回スケジュール
│   ├── prompts/{system|user|output_schema}/
│   └── browser/stealth.yaml
├── agent-core/
│   ├── Dockerfile / pyproject.toml
│   └── src/
│       ├── main.py
│       ├── core/              # skill_spec, skill_engine, skill_trace, safety
│       ├── skills/            # perception/ memory/ reasoning/ browser/
│       ├── adapters/          # ソースアダプタ実装（HN, GitHub, RSS, News等）
│       ├── scheduler/         # ルールベーススケジューラ
│       ├── models/
│       └── utils/
├── browser/                   # Playwright Stealth コンテナ
├── dashboard/                 # 監視 UI
├── data/                      # OUTPUT: 全て JSON
│   ├── traces/ / pipelines/
│   ├── qdrant/ / browser-profile/
│   └── outputs/ / logs/
└── docs/                      # 設計書
```

## 設計書

| # | ファイル | 内容 |
|---|---------|------|
| 0 | [目次](docs/0_index.md) | 設計書一覧 |
| 1 | [計画書本体](docs/1_plan.md) | 概要、アーキテクチャ、フェーズ計画 |
| 2 | [X ブラウザアクセス戦略](docs/2_x_browser_strategy.md) | bot検出対策、Stealth構成 |
| 3 | [Skill 定義](docs/3_skill_definition.md) | Skill YAML定義、依存関係 |
| 4 | [LLM プロンプト管理](docs/4_llm_prompt_context.md) | Working Memory、トークン制御 |
| 5 | [キャラクター](docs/5_character_framework.md) | 6層心理モデル |
| 6 | [意思決定ログ](docs/6_decisions.md) | レビュー結果、D1-D11の決定事項 |

元の統合設計書: `docs/1_agentarium_design.md`（4247行、アーカイブ）

## 実装フェーズ

| Phase | 目的 | Skill数 | 状態 |
|-------|------|---------|------|
| 0 | 技術検証（LLM速度、埋め込み日本語、Stealth） | — | **次に着手** |
| 1 | 情報収集 Agent（アダプタ + ルールベース巡回） | 10 | 未着手 |
| 2 | 記憶強化 + キャラクター + Discord + LLM駆動Skill選択 | +8 | 未着手 |
| 3 | 完全自律 + 感情・疲労モデル + デュアルプレゼンス | +6 | 未着手 |
| 4 | 発展・最適化（GraphRAG、VOICEVOX、ドリフト等） | +α | 未着手 |

## 開発コマンド

```bash
# Ollama（ホスト直接実行）
ollama serve
ollama run qwen3.5:35b-a3b

# MLX（検証用）
mlx_lm.server --model mlx-community/Qwen3.5-35B-A3B-4bit

# Docker
docker compose up -d
docker compose logs -f agent-core

# テスト
cd agent-core && python -m pytest tests/

# VNC（ブラウザ監視）
open vnc://localhost:5900
```

## 重要な設計原則

1. **Skill 単一責任** — 各 Skill は 1 つの機能に集中。Skill 間の状態共有禁止
2. **アダプタパターン** — 情報源はSkillではなくYAML設定で追加。共通基盤 + ソースアダプタ
3. **段階的複雑化** — Phase 1 はルールベース・静的値。LLM駆動・動的状態は Phase 2+
4. **過設計禁止** — プラグインシステム不要。dataclass + 関数参照
5. **情報源の多層化** — X に依存しない。HN / GitHub / RSS / ニュースサイト並列
6. **観測可能性** — 全 Skill 実行に SkillTrace 付与
7. **X 読取/書込分離** — Phase 1 は読取のみ。エンゲージメント自動化は禁止

## 主要な意思決定（詳細は docs/6_decisions.md）

- **D1**: LLMモデル → Qwen3.5-35B-A3B（Qwen3から更新）
- **D3**: Skill統合 → アダプタパターン（Phase 1: 20→10 Skill）
- **D4**: Skill選択 → Phase 1 ルールベース → Phase 2 LLM駆動
- **D7**: Qdrant → Phase 1 は 2コレクション（episodic/semantic）
- **D9**: キャラクター → Phase 1 は L1+L6 静的値のみ
