# Phase 0 検証手順書

> **目的**: コアパイプラインとブラウザ Stealth の実用性を具体的な手順で検証し、Phase 1 への Go/No-Go を判定する。

---

## 前半（1 週目）: コアパイプライン検証

### V1: Qwen3.5-35B-A3B 推論速度・JSON 出力品質

**セットアップ**:
```bash
# Ollama
ollama pull qwen3.5:35b-a3b
ollama pull qwen3.5:4b
OLLAMA_NUM_CTX=16384 ollama serve

# MLX（比較用）
pip install mlx-lm
mlx_lm.server --model mlx-community/Qwen3.5-35B-A3B-4bit --port 8080
```

**検証項目**:

| # | テスト | コマンド例 | 合格基準 |
|---|--------|-----------|---------|
| 1 | Ollama tok/s | `curl -s http://localhost:11434/api/generate -d '{"model":"qwen3.5:35b-a3b","prompt":"Hello","stream":false}' \| jq '.eval_count / (.eval_duration/1e9)'` | > 25 tok/s |
| 2 | MLX tok/s | 同様のベンチマーク | > 50 tok/s |
| 3 | JSON 出力安定性 | Skill 選択プロンプトを 10 回実行し、有効な JSON 出力率を計測 | 8/10 以上 |
| 4 | 日本語品質 | 日本語の記事要約タスクを 5 回実行 | 内容の正確性を目視確認 |

**JSON 出力テスト用プロンプト**:
```
以下の記事リストから、AIに関連するものを選択してJSON形式で回答してください。
{"articles": [{"title": "新型AIエージェントの登場", "id": 1}, {"title": "天気予報", "id": 2}]}
出力形式: {"selected": [{"id": number, "reason": "string"}]}
```

**判定**:
- Ollama > 25 tok/s **かつ** JSON 出力率 80%+ → Ollama で Phase 1
- MLX が 2 倍以上速く Docker 連携が可能 → MLX に切替
- 両方 < 20 tok/s → Qwen3.5-14B にフォールバック検討

---

### V2: 埋め込みモデル日本語品質

**セットアップ**:
```bash
ollama pull nomic-embed-text
# multilingual-e5-base は Python 経由で検証
pip install sentence-transformers
```

**テストケース**（日英混在の技術文書）:

| # | クエリ | 期待される類似ドキュメント |
|---|--------|------------------------|
| 1 | "Qwen3.5 の MoE アーキテクチャ" | MoE/Mixture of Experts 関連の記事 |
| 2 | "ブラウザ自動化の bot 検出" | Playwright Stealth / rebrowser 関連 |
| 3 | "autonomous AI agent" | 自律型 AI エージェント関連（日本語記事でもヒットすべき） |
| 4 | "Qdrant ベクトル検索" | Qdrant / RAG / 埋め込み関連 |

**検証スクリプト**:
```python
# 疑似コード: 各モデルでの類似度比較
from sentence_transformers import SentenceTransformer

models = ["nomic-ai/nomic-embed-text-v1.5", "intfloat/multilingual-e5-base"]
for model_name in models:
    model = SentenceTransformer(model_name)
    query_emb = model.encode("Qwen3.5 の MoE アーキテクチャ")
    doc_emb = model.encode("Mixture of Experts enables efficient inference")
    similarity = cosine_similarity(query_emb, doc_emb)
    print(f"{model_name}: {similarity:.3f}")
```

**判定**:
- nomic-embed-text の日英クロスリンガル類似度 > 0.6 → nomic で十分
- multilingual-e5 が nomic より 20%+ 高精度 → multilingual-e5 を採用
- 両方 < 0.5 → 日本語特化モデル（e5-mistral 等）を追加検討

---

### V3: Qdrant 基本パイプライン

**セットアップ**:
```bash
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant:latest
```

**検証**:
```python
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct

client = QdrantClient(host="localhost", port=6333)

# コレクション作成
client.create_collection(
    collection_name="episodic",
    vectors_config=VectorParams(size=768, distance=Distance.COSINE)
)
client.create_collection(
    collection_name="semantic",
    vectors_config=VectorParams(size=768, distance=Distance.COSINE)
)

# ポイント書き込み（store_episodic 相当）
client.upsert(
    collection_name="episodic",
    points=[PointStruct(id=1, vector=[0.1]*768, payload={
        "timestamp": "2026-03-31T14:00:00+09:00",
        "skill": "browse_source",
        "source": "hacker_news",
        "result_count": 15,
        "duration_ms": 2400
    })]
)

# 検索（recall_related 相当）
results = client.search(
    collection_name="semantic",
    query_vector=[0.1]*768,
    limit=5
)
```

**合格基準**: 書き込み・検索が正常動作し、レイテンシ < 100ms

---

### V4: 代替ソース検証

| ソース | 検証コマンド | 合格基準 |
|--------|------------|---------|
| HN API | `curl -s "https://hacker-news.firebaseio.com/v0/topstories.json" \| jq '.[0:5]'` | JSON 配列が返る |
| GitHub | ブラウザで `https://github.com/trending` にアクセスし DOM 要素を確認 | `article.Box-row` が存在 |
| RSS | `curl -s "https://hnrss.org/frontpage" \| head -20` | XML が返る |
| Yahoo News | ブラウザで DOM セレクタ `.newsFeed_item` を確認 | 要素が存在 |

---

### V5: SkillSpec YAML → dataclass ロード

Phase 0 では最低限の SkillSpec ロード機能を検証:

```python
import yaml
from dataclasses import dataclass

@dataclass
class SkillSpec:
    name: str
    category: str
    description: str
    # ... 最小限のフィールド

with open("config/sources/hacker_news.yaml") as f:
    data = yaml.safe_load(f)
    # YAML → dataclass 変換が正常に動作するか
```

**合格基準**: config/sources/ 内の全 YAML が正常にロードできる

---

## 後半（2 週目）: ブラウザ・X 検証

### V6: Playwright Stealth

**セットアップ**:
```bash
# browser コンテナ起動（docker-compose.yml 作成後）
docker compose up -d browser
# または直接実行
pip install rebrowser-playwright
playwright install chromium
```

**検証**:

| # | テスト | 方法 | 合格基準 |
|---|--------|------|---------|
| 1 | bot.sannysoft.com | rebrowser-playwright で sannysoft にアクセスし全項目を確認 | 全項目 green |
| 2 | browserscan.net | CDP 検出テスト | "No automation detected" |
| 3 | WebGL/Canvas | fingerprint 一致確認 | 実マシンの GPU 情報と一致 |

### V7: X セッション・アクセス

2_x_browser_strategy.md Section 8 の Go/No-Go 判定に従う。

| # | テスト | 合格基準 |
|---|--------|---------|
| 1 | 手動ログイン後 24h セッション維持 | セッション有効 |
| 2 | タイムライン閲覧 10 回 | 8/10 成功 |
| 3 | 検索 5 回 | 3/5 成功 |
| 4 | 72 時間連続運用 | アカウント停止なし |

---

## Go / No-Go 判定マトリクス

| 検証 | 結果 | Phase 1 への影響 |
|------|------|-----------------|
| V1 合格 + V2 合格 + V3 合格 | **コアパイプライン Go** | Phase 1 着手可能 |
| V1 不合格 | **モデル見直し** | Qwen3.5-14B or 別モデルで再検証 |
| V2 不合格 | **埋め込みモデル変更** | multilingual-e5 に切替して再検証 |
| V6 合格 + V7 合格 | **X アクセス Go** | patrol.yaml の x_timeline を enabled: true に |
| V6 合格 + V7 不合格 | **X 条件付き** | X は低頻度 or 断念、代替ソースで Phase 1 |
| V6 不合格 | **Stealth 見直し** | Node.js rebrowser or 住宅プロキシ検討 |

**重要**: V1-V5 が合格すれば、V6-V7 の結果に関わらず Phase 1 に進める。
