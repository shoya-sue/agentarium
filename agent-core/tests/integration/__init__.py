"""
tests/integration/ — 統合テストパッケージ

実サービス（Qdrant / Ollama / embed server）に対して
Phase 1 Skill が正しく動作するかを検証する。

前提条件:
  - Qdrant:  localhost:6333
  - Ollama:  localhost:11434 (qwen3.5:35b-a3b)
  - embed:   localhost:8001  (multilingual-e5-base)

スキップ条件:
  各テストは pytest.mark.skipif でサービス未起動時に自動スキップ。
"""
