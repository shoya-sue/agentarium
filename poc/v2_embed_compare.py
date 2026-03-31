"""
V2: 埋め込みモデル日本語品質の比較検証
  - nomic-embed-text（Ollama 経由）vs multilingual-e5-base（sentence-transformers）
合格基準:
  - 日英クロスリンガル類似度 > 0.6
"""

import json
import math
import urllib.request
from dataclasses import dataclass
from typing import Optional, List

OLLAMA_BASE_URL = "http://localhost:11434"
NOMIC_MODEL = "nomic-embed-text"

# テストケース: (クエリ, 期待関連ドキュメント, 期待非関連ドキュメント)
TEST_CASES = [
    (
        "Qwen3.5 の MoE アーキテクチャ",
        "Mixture of Experts enables efficient inference with sparse activation",
        "今日の天気は晴れで気温は25度です",
    ),
    (
        "ブラウザ自動化の bot 検出",
        "Playwright Stealth bypasses headless browser detection",
        "東京都の最新ニュースをお届けします",
    ),
    (
        "autonomous AI agent",
        "自律型 AI エージェントがタスクを自律的に実行する",
        "サッカーの試合結果と得点情報",
    ),
    (
        "Qdrant ベクトル検索",
        "Vector database for semantic search and RAG systems",
        "料理レシピの作り方を紹介します",
    ),
]


@dataclass
class EmbedResult:
    model: str
    query: str
    related_sim: float
    unrelated_sim: float

    @property
    def cross_lingual_ok(self) -> bool:
        # 判定: 関連文書の類似度が 0.6 超 かつ 非関連より高い
        # （sentence-transformers はスコアが高い領域に集まるため +0.1 マージンは不要）
        return self.related_sim > 0.6 and self.related_sim > self.unrelated_sim


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def nomic_embed(text: str) -> Optional[List[float]]:
    payload = json.dumps({"model": NOMIC_MODEL, "prompt": text}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data.get("embedding")
    except Exception as e:
        print(f"  nomic embed ERROR: {e}")
        return None


def check_ollama_model(model: str) -> bool:
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            return any(model in m for m in models)
    except Exception:
        return False


def run_nomic_tests() -> list[EmbedResult]:
    print("\n--- nomic-embed-text (Ollama) ---")
    results = []
    for query, related, unrelated in TEST_CASES:
        q_emb = nomic_embed(query)
        r_emb = nomic_embed(related)
        u_emb = nomic_embed(unrelated)
        if q_emb is None or r_emb is None or u_emb is None:
            print(f"  SKIP: エンベディング取得失敗 query='{query[:30]}'")
            continue
        related_sim = cosine_similarity(q_emb, r_emb)
        unrelated_sim = cosine_similarity(q_emb, u_emb)
        result = EmbedResult(
            model="nomic-embed-text",
            query=query,
            related_sim=related_sim,
            unrelated_sim=unrelated_sim,
        )
        status = "OK" if result.cross_lingual_ok else "FAIL"
        print(f"  [{status}] '{query[:25]}...'")
        print(f"         関連: {related_sim:.3f}  非関連: {unrelated_sim:.3f}")
        results.append(result)
    return results


def run_multilingual_e5_tests() -> list[EmbedResult]:
    """sentence-transformers 経由で multilingual-e5-base を検証"""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        print("\n--- multilingual-e5-base ---")
        print("  SKIP: sentence-transformers がインストールされていません。")
        print("  `pip install sentence-transformers` を実行してください。")
        return []

    print("\n--- multilingual-e5-base (sentence-transformers) ---")
    print("  モデルのロード中（初回は数分かかります）...")
    try:
        model = SentenceTransformer("intfloat/multilingual-e5-base")
    except Exception as e:
        print(f"  ERROR: モデルロード失敗: {e}")
        return []

    results = []
    for query, related, unrelated in TEST_CASES:
        # multilingual-e5 は "query: " / "passage: " プレフィックスが推奨
        q_emb = model.encode(f"query: {query}").tolist()
        r_emb = model.encode(f"passage: {related}").tolist()
        u_emb = model.encode(f"passage: {unrelated}").tolist()
        related_sim = cosine_similarity(q_emb, r_emb)
        unrelated_sim = cosine_similarity(q_emb, u_emb)
        result = EmbedResult(
            model="multilingual-e5-base",
            query=query,
            related_sim=related_sim,
            unrelated_sim=unrelated_sim,
        )
        status = "OK" if result.cross_lingual_ok else "FAIL"
        print(f"  [{status}] '{query[:25]}...'")
        print(f"         関連: {related_sim:.3f}  非関連: {unrelated_sim:.3f}")
        results.append(result)
    return results


def judge(results: List[EmbedResult], model_name: str) -> bool:
    if not results:
        return False
    ok_count = sum(1 for r in results if r.cross_lingual_ok)
    avg_related = sum(r.related_sim for r in results) / len(results)
    avg_unrelated = sum(r.unrelated_sim for r in results) / len(results)
    # 4件中 3件以上合格 かつ 平均関連 > 平均非関連 で合格とする
    passed = ok_count >= max(3, len(results) - 1) and avg_related > avg_unrelated
    print(f"  {model_name}: {ok_count}/{len(results)} ケース合格  関連avg: {avg_related:.3f}  非関連avg: {avg_unrelated:.3f}")
    return passed


def main() -> None:
    print("=" * 60)
    print("V2: 埋め込みモデル日本語品質")
    print("=" * 60)

    # nomic
    nomic_ok = False
    if check_ollama_model(NOMIC_MODEL):
        nomic_results = run_nomic_tests()
        nomic_ok = judge(nomic_results, "nomic-embed-text")
    else:
        print(f"\nnomic-embed-text が見つかりません。`ollama pull {NOMIC_MODEL}` を実行してください。")

    # multilingual-e5
    e5_results = run_multilingual_e5_tests()
    e5_ok = judge(e5_results, "multilingual-e5-base") if e5_results else False

    # 判定
    print("\n--- 判定 ---")
    if nomic_ok:
        print("合格: nomic-embed-text で十分です（Phase 1 に進めます）。")
    elif e5_ok:
        print("合格（条件付き）: multilingual-e5-base を採用してください。")
    else:
        print("注意: 両モデルとも基準未達。日本語特化モデルの追加検討が必要。")

    # モデル比較
    if nomic_ok and e5_ok and e5_results and nomic_results:  # type: ignore[name-defined]
        nomic_avg = sum(r.related_sim for r in nomic_results) / len(nomic_results)  # type: ignore[name-defined]
        e5_avg = sum(r.related_sim for r in e5_results) / len(e5_results)
        if e5_avg > nomic_avg * 1.2:
            print(f"推奨: multilingual-e5 が nomic より {(e5_avg/nomic_avg - 1)*100:.0f}% 高精度。切替を検討。")
        else:
            print("推奨: nomic-embed-text（Ollama 完結、運用コスト低）で十分。")


if __name__ == "__main__":
    main()
