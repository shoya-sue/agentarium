"""
embed/server.py — multilingual-e5-base 埋め込みサーバー

Phase 0 V2 検証結果:
  - nomic-embed-text: 日英クロスリンガル avg 0.484（基準 0.6 未達）→ 不採用
  - multilingual-e5-base: 関連 avg 0.810 → 採用

API:
  POST /embed
  Request:  {"texts": ["文字列1", "文字列2", ...]}
  Response: {"embeddings": [[float, ...], ...], "dim": 768}

  GET /health
  Response: {"status": "ok", "model": "intfloat/multilingual-e5-base", "dim": 768}
"""

import logging
import os
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

# ──────────────────────────────────────────────
# 設定
# ──────────────────────────────────────────────
MODEL_NAME = os.environ.get("MODEL_NAME", "intfloat/multilingual-e5-base")
PORT = int(os.environ.get("PORT", "8001"))
VECTOR_DIM = 768

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# モデル（グローバルシングルトン）
# ──────────────────────────────────────────────
_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    """モデルを返す（未初期化なら RuntimeError）"""
    if _model is None:
        raise RuntimeError("モデルが未初期化です")
    return _model


# ──────────────────────────────────────────────
# FastAPI ライフサイクル
# ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """起動時にモデルをロード、終了時に解放"""
    global _model
    logger.info("モデルをロード中: %s", MODEL_NAME)
    _model = SentenceTransformer(MODEL_NAME)

    # 次元数チェック
    test_emb = _model.encode(["warmup"], normalize_embeddings=True)
    actual_dim = len(test_emb[0])
    if actual_dim != VECTOR_DIM:
        logger.warning(
            "ベクトル次元が想定と異なります: expected=%d, actual=%d",
            VECTOR_DIM,
            actual_dim,
        )
    logger.info("モデルロード完了（dim=%d）", actual_dim)
    yield
    # 終了処理（特になし）
    _model = None
    logger.info("サーバー終了")


app = FastAPI(
    title="Agentarium Embed Server",
    description="multilingual-e5-base を使った日英クロスリンガル埋め込み API",
    version="1.0.0",
    lifespan=lifespan,
)


# ──────────────────────────────────────────────
# スキーマ
# ──────────────────────────────────────────────
class EmbedRequest(BaseModel):
    texts: list[str]


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]
    dim: int


class HealthResponse(BaseModel):
    status: str
    model: str
    dim: int


# ──────────────────────────────────────────────
# エンドポイント
# ──────────────────────────────────────────────
@app.post("/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest) -> EmbedResponse:
    """テキストリストをベクトル化して返す"""
    if not request.texts:
        raise HTTPException(status_code=400, detail="texts は空にできません")

    model = get_model()

    # multilingual-e5 は "query: " / "passage: " プレフィックスが推奨だが
    # Agentarium では統一的に passage として扱う（検索クエリも同形式で比較）
    prefixed = [f"passage: {t}" for t in request.texts]

    embeddings: np.ndarray = model.encode(
        prefixed,
        normalize_embeddings=True,
        batch_size=32,
        show_progress_bar=False,
    )

    return EmbedResponse(
        embeddings=embeddings.tolist(),
        dim=embeddings.shape[1],
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """ヘルスチェック"""
    return HealthResponse(
        status="ok",
        model=MODEL_NAME,
        dim=VECTOR_DIM,
    )


# ──────────────────────────────────────────────
# エントリポイント
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=PORT,
        log_level="info",
    )
