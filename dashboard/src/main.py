"""
Agentarium Dashboard — FastAPI サーバー

エンドポイント:
  GET /                     → index.html
  GET /api/events           → SSE ストリーム（新規トレース検知時にイベント送信）
  GET /api/traces           → 最新トレース一覧（?limit=50）
  GET /api/traces/{id}      → トレース詳細
  GET /api/qdrant/stats     → Qdrant コレクション統計
  GET /api/scheduler/states → スケジューラ状態
"""
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .qdrant_stats import get_qdrant_stats
from .scheduler_reader import read_scheduler_states
from .watcher import watch_traces

logger = logging.getLogger(__name__)

# 環境変数から設定を読み込む
DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/app/config"))
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
STATIC_DIR = Path(__file__).parent.parent / "static"

# SSE ブロードキャスト用: 接続中クライアントのキュー一覧
_subscribers: list[asyncio.Queue] = []


async def broadcast(event: dict) -> None:
    """全 SSE クライアントにイベントを送信する"""
    for q in list(_subscribers):
        try:
            await q.put(event)
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリ起動時にファイル監視タスクを起動し、終了時にキャンセルする"""
    traces_dir = DATA_DIR / "traces"
    task = asyncio.create_task(watch_traces(traces_dir, broadcast))
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Agentarium Dashboard", lifespan=lifespan)

# /static 以下の静的ファイルをマウント
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def get_index():
    """ダッシュボードのメインページを返す"""
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(str(index_file))


@app.get("/api/events")
async def sse_events():
    """SSE ストリーム: 新規 SkillTrace 検知時にイベントを送信する"""
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.append(q)

    async def event_generator():
        # 接続確認イベント
        yield "data: {\"type\": \"connected\"}\n\n"
        try:
            while True:
                event = await q.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            # クライアント切断時にキューを削除
            try:
                _subscribers.remove(q)
            except ValueError:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/traces")
async def list_traces(limit: int = 50):
    """最新の SkillTrace ファイル一覧を返す"""
    traces_dir = DATA_DIR / "traces"
    if not traces_dir.exists():
        return {"traces": []}

    # 更新日時でソートして最新 limit 件を返す
    trace_files = sorted(
        traces_dir.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:limit]

    traces = []
    for f in trace_files:
        try:
            traces.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            # 読み込みエラーは無視
            pass

    return {"traces": traces}


@app.get("/api/traces/{trace_id}")
async def get_trace(trace_id: str):
    """指定された trace_id のトレース詳細を返す"""
    traces_dir = DATA_DIR / "traces"

    # trace_id は拡張子なし or .json 付きを両方サポート
    candidates = [
        traces_dir / f"{trace_id}.json",
        traces_dir / trace_id,
    ]
    for path in candidates:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc

    raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")


@app.get("/api/qdrant/stats")
async def qdrant_stats():
    """Qdrant コレクション統計を返す（Qdrant 停止中でも 200 を返す）"""
    return await get_qdrant_stats(QDRANT_URL)


@app.get("/api/scheduler/states")
async def scheduler_states():
    """PatrolScheduler の現在状態を返す"""
    return read_scheduler_states(DATA_DIR, CONFIG_DIR)
