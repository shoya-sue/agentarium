# Agentarium — 統合設計書

**リポジトリ名**: `agentarium`
**プロジェクト名**: Agentarium — Autonomous Personal Agent
**系譜**: Zethi / Prako Discord Agent → 発展型
**作成日**: 2026-03-31
**ステータス**: 設計策定完了 + レビュー済み（D1-D11 反映）
**元ファイル**: `1_agentarium_design.md`（分割前のオリジナル）

---

## 設計書一覧

| # | ファイル | 内容 |
|---|---------|------|
| 1 | [計画書本体](1_plan.md) | プロジェクト概要、アーキテクチャ、Skill設計、記憶、フェーズ計画 |
| 2 | [X ブラウザアクセス戦略](2_x_browser_strategy.md) | bot検出対策、Stealth構成、HumanBehavior |
| 3 | [Skill 定義 + YAML テンプレート](3_skill_definition.md) | 全28 Skill の YAML 定義、アダプタパターン、依存関係 |
| 4 | [LLM プロンプト / コンテキスト管理](4_llm_prompt_context.md) | Working Memory、プロンプトテンプレート、トークン制御 |
| 5 | [キャラクターフレームワーク](5_character_framework.md) | 6層心理モデル、感情→行動影響 |

## レビュー・意思決定

| # | ファイル | 内容 |
|---|---------|------|
| - | [設計レビュー・意思決定ログ](6_decisions.md) | 分析結果とアーキテクチャ意思決定（D1-D11） |
| - | [Phase 0 検証手順書](7_phase0_verification.md) | 具体的なコマンド・期待値・Go/No-Go 判定基準 |
