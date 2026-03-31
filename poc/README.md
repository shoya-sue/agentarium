# Phase 0 検証スクリプト

コアパイプラインの実用性を確認するための最小限の検証スクリプト群。
Phase 1 着手前に V1〜V5 が全て合格であることを確認すること。

## 前提条件

```bash
# Python 依存
pip install qdrant-client sentence-transformers pyyaml requests

# Ollama（ホスト直接実行）
ollama serve
ollama pull qwen3.5:35b-a3b
ollama pull nomic-embed-text

# Qdrant（Docker）
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant:latest
```

## 検証一覧

| スクリプト | 検証項目 | 合格基準 |
|-----------|---------|---------|
| `v1_llm_bench.py` | Ollama/MLX 推論速度・JSON 出力安定性 | > 25 tok/s, JSON 成功率 8/10 |
| `v2_embed_compare.py` | 埋め込みモデル日本語品質（nomic vs multilingual-e5） | 日英クロス類似度 > 0.6 |
| `v3_qdrant_test.py` | Qdrant 書き込み・検索パイプライン | 書き込み/検索成功、< 100ms |
| `v4_sources_test.py` | ソースアダプタ疎通（HN API / RSS） | HTTP 200 + 正常パース |
| `v5_yaml_load.py` | SkillSpec YAML → dataclass ロード | config/sources/ 全 YAML 正常ロード |

## 実行順序

```bash
cd poc/

# 1. LLM 速度確認（Ollama が起動済みであること）
python v1_llm_bench.py

# 2. 埋め込みモデル比較（初回はモデルDLあり）
python v2_embed_compare.py

# 3. Qdrant 疎通（Docker コンテナが起動済みであること）
python v3_qdrant_test.py

# 4. ソースアダプタ疎通（インターネット接続が必要）
python v4_sources_test.py

# 5. YAML ロード（依存なし、いつでも実行可）
python v5_yaml_load.py
```

## V6/V7（週2: ブラウザ・X 検証）

docs/7_phase0_verification.md を参照。
Docker Compose でブラウザコンテナを起動してから手動で実施する。
