"""
V3: Qdrant 基本パイプライン検証
  - episodic / semantic 2コレクション作成
  - store_episodic 相当: ポイント書き込み
  - recall_related 相当: ベクトル検索
合格基準:
  - 書き込み・検索が正常動作
  - 検索レイテンシ < 100ms
"""

import random
import time
from datetime import datetime, timezone, timedelta

QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
VECTOR_DIM = 768  # nomic-embed-text / multilingual-e5 の次元数

JST = timezone(timedelta(hours=9))


def now_jst() -> str:
    return datetime.now(JST).isoformat()


def check_qdrant() -> bool:
    try:
        from qdrant_client import QdrantClient  # type: ignore
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=5)
        client.get_collections()
        return True
    except Exception as e:
        print(f"  Qdrant 接続失敗: {e}")
        return False


def random_vector(dim: int) -> list[float]:
    v = [random.gauss(0, 1) for _ in range(dim)]
    norm = sum(x * x for x in v) ** 0.5
    return [x / norm for x in v]


def run_episodic_test(client) -> bool:  # type: ignore[no-untyped-def]
    from qdrant_client.models import VectorParams, Distance, PointStruct  # type: ignore

    collection = "episodic_poc"

    # コレクション作成（既存なら再作成）
    try:
        client.delete_collection(collection)
    except Exception:
        pass

    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
    )
    print(f"  コレクション作成: {collection}")

    # store_episodic 相当: Skill 実行ログを書き込む
    points = [
        PointStruct(
            id=i,
            vector=random_vector(VECTOR_DIM),
            payload={
                "timestamp": now_jst(),
                "skill": "browse_source",
                "source": f"hacker_news_{i}",
                "result_count": random.randint(5, 20),
                "duration_ms": random.randint(500, 3000),
            },
        )
        for i in range(1, 11)
    ]

    t0 = time.perf_counter()
    client.upsert(collection_name=collection, points=points)
    write_ms = (time.perf_counter() - t0) * 1000
    print(f"  書き込み 10件: {write_ms:.1f}ms")

    # 検索（qdrant-client v1.x: query_points を使用）
    query_vec = random_vector(VECTOR_DIM)
    t0 = time.perf_counter()
    response = client.query_points(collection_name=collection, query=query_vec, limit=5)
    results = response.points
    search_ms = (time.perf_counter() - t0) * 1000
    print(f"  検索結果 {len(results)}件: {search_ms:.1f}ms")

    ok = len(results) == 5 and search_ms < 100
    print(f"  [{'OK' if ok else 'FAIL'}] 検索レイテンシ {search_ms:.1f}ms (基準: < 100ms)")
    return ok


def run_semantic_test(client) -> bool:  # type: ignore[no-untyped-def]
    from qdrant_client.models import VectorParams, Distance, PointStruct, Filter, FieldCondition, MatchValue  # type: ignore

    collection = "semantic_poc"

    try:
        client.delete_collection(collection)
    except Exception:
        pass

    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
    )
    print(f"\n  コレクション作成: {collection}")

    # store_semantic 相当: 記事コンテンツを書き込む
    docs = [
        {"title": "Qwen3.5 MoE アーキテクチャの詳細", "source": "hacker_news", "lang": "ja"},
        {"title": "Playwright Stealth bot detection bypass", "source": "github_trending", "lang": "en"},
        {"title": "Qdrant vector search tutorial", "source": "rss", "lang": "en"},
        {"title": "自律型 AI エージェントの設計パターン", "source": "yahoo_news", "lang": "ja"},
        {"title": "Python asyncio best practices", "source": "hacker_news", "lang": "en"},
    ]
    points = [
        PointStruct(
            id=i + 100,
            vector=random_vector(VECTOR_DIM),
            payload={**doc, "stored_at": now_jst()},
        )
        for i, doc in enumerate(docs)
    ]

    client.upsert(collection_name=collection, points=points)
    print(f"  書き込み {len(points)}件")

    # ペイロードフィルタ + 検索（qdrant-client v1.x: query_points を使用）
    t0 = time.perf_counter()
    response = client.query_points(
        collection_name=collection,
        query=random_vector(VECTOR_DIM),
        query_filter=Filter(
            must=[FieldCondition(key="lang", match=MatchValue(value="ja"))]
        ),
        limit=3,
    )
    results = response.points
    search_ms = (time.perf_counter() - t0) * 1000
    print(f"  フィルタ検索 (lang=ja): {len(results)}件 {search_ms:.1f}ms")

    ok = search_ms < 100
    print(f"  [{'OK' if ok else 'FAIL'}] フィルタ検索レイテンシ {search_ms:.1f}ms")
    return ok


def cleanup(client) -> None:  # type: ignore[no-untyped-def]
    for col in ["episodic_poc", "semantic_poc"]:
        try:
            client.delete_collection(col)
        except Exception:
            pass
    print("\n  クリーンアップ完了（テスト用コレクション削除）")


def main() -> None:
    print("=" * 60)
    print("V3: Qdrant 基本パイプライン")
    print("=" * 60)

    if not check_qdrant():
        print("ERROR: Qdrant が起動していません。")
        print("  docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant:latest")
        return

    print("  Qdrant 接続: OK")

    try:
        from qdrant_client import QdrantClient  # type: ignore
    except ImportError:
        print("ERROR: qdrant-client がインストールされていません。`pip install qdrant-client`")
        return

    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    print("\n--- episodic コレクション (Skill 実行ログ) ---")
    episodic_ok = run_episodic_test(client)

    print("\n--- semantic コレクション (記事コンテンツ) ---")
    semantic_ok = run_semantic_test(client)

    cleanup(client)

    print("\n--- 判定 ---")
    if episodic_ok and semantic_ok:
        print("合格: Qdrant パイプラインは正常動作しています。")
    else:
        if not episodic_ok:
            print("注意: episodic コレクションの検索レイテンシが基準超え。")
        if not semantic_ok:
            print("注意: semantic コレクションの検索レイテンシが基準超え。")
        print("→ Qdrant のリソース設定を見直してください。")


if __name__ == "__main__":
    main()
