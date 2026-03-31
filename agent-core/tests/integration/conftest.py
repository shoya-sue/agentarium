"""
tests/integration/conftest.py — 統合テスト共通フィクスチャ

サービスの疎通確認と、テスト用コレクション名の管理を行う。
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

# src/ を Python パスに追加
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

# ──────────────────────────────────────────────
# サービスエンドポイント定数
# ──────────────────────────────────────────────
QDRANT_URL = "http://localhost:6333"
OLLAMA_URL = "http://localhost:11434"
EMBED_URL = "http://localhost:8001"

# テスト用コレクション名（本番と分離）
TEST_EPISODIC_COLLECTION = "test_integration_episodic"
TEST_SEMANTIC_COLLECTION = "test_integration_semantic"


# ──────────────────────────────────────────────
# サービス疎通チェック関数
# ──────────────────────────────────────────────

def _is_qdrant_available() -> bool:
    """Qdrant が起動しているか確認する"""
    try:
        resp = httpx.get(f"{QDRANT_URL}/collections", timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False


def _is_ollama_available() -> bool:
    """Ollama が起動していてモデルが使えるか確認する"""
    try:
        resp = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3.0)
        if resp.status_code != 200:
            return False
        models = [m["name"] for m in resp.json().get("models", [])]
        # qwen3.5:35b-a3b があれば OK
        return any("qwen3.5" in m for m in models)
    except Exception:
        return False


def _is_embed_available() -> bool:
    """embed サーバーが起動しているか確認する"""
    try:
        resp = httpx.get(f"{EMBED_URL}/health", timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False


# ──────────────────────────────────────────────
# pytest marks（サービス未起動時スキップ）
# ──────────────────────────────────────────────

requires_qdrant = pytest.mark.skipif(
    not _is_qdrant_available(),
    reason="Qdrant が localhost:6333 で起動していません",
)

requires_ollama = pytest.mark.skipif(
    not _is_ollama_available(),
    reason="Ollama (qwen3.5:35b-a3b) が localhost:11434 で起動していません",
)

requires_embed = pytest.mark.skipif(
    not _is_embed_available(),
    reason="embed サーバーが localhost:8001 で起動していません",
)

requires_all_services = pytest.mark.skipif(
    not (_is_qdrant_available() and _is_embed_available()),
    reason="Qdrant または embed サーバーが起動していません",
)


# ──────────────────────────────────────────────
# テスト用コレクション管理フィクスチャ
# ──────────────────────────────────────────────

@pytest.fixture(scope="session")
def qdrant_client():
    """テスト用 Qdrant クライアント（セッションスコープ）"""
    if not _is_qdrant_available():
        pytest.skip("Qdrant が起動していません")
    from qdrant_client import QdrantClient
    return QdrantClient(host="localhost", port=6333)


@pytest.fixture(autouse=True, scope="session")
def cleanup_test_collections(qdrant_client):
    """セッション終了後にテスト用コレクションを削除する"""
    yield
    # テスト後のクリーンアップ
    for col_name in [TEST_EPISODIC_COLLECTION, TEST_SEMANTIC_COLLECTION]:
        try:
            existing = [c.name for c in qdrant_client.get_collections().collections]
            if col_name in existing:
                qdrant_client.delete_collection(col_name)
        except Exception as exc:
            print(f"[cleanup] コレクション削除エラー: {col_name} — {exc}")


@pytest.fixture
def config_dir() -> Path:
    """agentarium config ディレクトリのパスを返す"""
    return Path(__file__).parent.parent.parent.parent / "config"
