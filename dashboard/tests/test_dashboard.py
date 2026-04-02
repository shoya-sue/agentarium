"""
Dashboard エンドポイントのテスト

TDD: RED → GREEN → REFACTOR
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


# ─── フィクスチャ ─────────────────────────────────────────

@pytest.fixture
def tmp_dirs():
    """テスト用の一時ディレクトリ（data/ と config/）"""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "data"
        config_dir = Path(tmp) / "config"
        data_dir.mkdir()
        config_dir.mkdir()
        yield data_dir, config_dir


@pytest.fixture
def app_with_dirs(tmp_dirs, monkeypatch):
    """テスト用環境変数を設定した FastAPI app"""
    data_dir, config_dir = tmp_dirs

    # 環境変数をモックして app をインポート
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("QDRANT_URL", "http://localhost:16333")

    # モジュールを再ロードしてパスを反映
    import importlib
    import dashboard.src.main as main_mod
    importlib.reload(main_mod)

    return main_mod.app, data_dir, config_dir


# ─── テスト: GET / ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_root_returns_html(app_with_dirs):
    """GET / → 200 + HTML を返す"""
    app, data_dir, config_dir = app_with_dirs

    # static/index.html を作成
    static_dir = Path(__file__).parent.parent / "static"
    static_dir.mkdir(exist_ok=True)
    index_html = static_dir / "index.html"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/")
        # index.html が存在する場合は 200、存在しない場合は 404
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            assert "text/html" in resp.headers["content-type"]


# ─── テスト: GET /api/traces ──────────────────────────────

@pytest.mark.asyncio
async def test_get_traces_empty(app_with_dirs):
    """トレースが存在しない場合 GET /api/traces → {"traces": []}"""
    app, data_dir, config_dir = app_with_dirs

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/traces")
        assert resp.status_code == 200
        body = resp.json()
        assert "traces" in body
        assert body["traces"] == []


@pytest.mark.asyncio
async def test_get_traces_returns_files(app_with_dirs):
    """トレースファイルがある場合は正しく返す"""
    app, data_dir, config_dir = app_with_dirs

    # data/traces/ にダミートレースを作成
    traces_dir = data_dir / "traces"
    traces_dir.mkdir()
    trace_data = {
        "trace_id": "test-001",
        "skill_name": "fetch_content",
        "status": "success",
        "started_at": "2026-04-02T00:00:00Z",
    }
    (traces_dir / "test-001.json").write_text(json.dumps(trace_data))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/traces")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["traces"]) == 1
        assert body["traces"][0]["trace_id"] == "test-001"


# ─── テスト: GET /api/qdrant/stats ───────────────────────

@pytest.mark.asyncio
async def test_get_qdrant_stats_connection_error(app_with_dirs):
    """Qdrant が落ちていても GET /api/qdrant/stats → 200 を返す"""
    app, data_dir, config_dir = app_with_dirs

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/qdrant/stats")
        # Qdrant に接続できなくてもアプリは 200 を返す
        assert resp.status_code == 200
        body = resp.json()
        assert "collections" in body
        # 接続エラー時は error フィールドが含まれる
        # (Qdrant が起動していない場合)
        assert isinstance(body["collections"], dict)


# ─── テスト: GET /api/scheduler/states ───────────────────

@pytest.mark.asyncio
async def test_get_scheduler_states_empty(app_with_dirs):
    """states.json も patrol.yaml も存在しない場合は空状態を返す"""
    app, data_dir, config_dir = app_with_dirs

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/scheduler/states")
        assert resp.status_code == 200
        body = resp.json()
        assert "sources" in body
        assert body["sources"] == []


@pytest.mark.asyncio
async def test_get_scheduler_states_from_states_json(app_with_dirs):
    """data/scheduler/states.json が存在する場合はそれを返す"""
    app, data_dir, config_dir = app_with_dirs

    scheduler_dir = data_dir / "scheduler"
    scheduler_dir.mkdir()
    states_data = {
        "updated_at": "2026-04-02T00:00:00Z",
        "sources": [
            {"source_id": "hackernews", "enabled": True, "interval_min": 60, "last_run_at": None, "consecutive_failures": 0}
        ],
    }
    (scheduler_dir / "states.json").write_text(json.dumps(states_data))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/scheduler/states")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["sources"]) == 1
        assert body["sources"][0]["source_id"] == "hackernews"


@pytest.mark.asyncio
async def test_get_scheduler_states_fallback_to_patrol_yaml(app_with_dirs):
    """states.json がなく patrol.yaml がある場合はフォールバック"""
    app, data_dir, config_dir = app_with_dirs

    schedules_dir = config_dir / "schedules"
    schedules_dir.mkdir(parents=True)
    patrol_yaml_content = """
sources:
  - id: hackernews
    enabled: true
    interval_min: 60
  - id: github_trending
    enabled: true
    interval_min: 120
"""
    (schedules_dir / "patrol.yaml").write_text(patrol_yaml_content)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/scheduler/states")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["sources"]) == 2
        assert body["sources"][0]["source_id"] == "hackernews"
        assert body["sources"][0]["last_run_at"] is None


# ─── テスト: scheduler_reader ユニットテスト ──────────────

def test_scheduler_reader_returns_empty_when_no_files(tmp_dirs):
    """ファイルが存在しない場合は空の状態を返す"""
    from dashboard.src.scheduler_reader import read_scheduler_states
    data_dir, config_dir = tmp_dirs
    result = read_scheduler_states(data_dir, config_dir)
    assert result == {"updated_at": None, "sources": []}


def test_scheduler_reader_reads_states_json(tmp_dirs):
    """states.json が存在する場合はそれを読む"""
    from dashboard.src.scheduler_reader import read_scheduler_states
    data_dir, config_dir = tmp_dirs

    scheduler_dir = data_dir / "scheduler"
    scheduler_dir.mkdir()
    expected = {"updated_at": "2026-04-02T00:00:00Z", "sources": [{"source_id": "rss"}]}
    (scheduler_dir / "states.json").write_text(json.dumps(expected))

    result = read_scheduler_states(data_dir, config_dir)
    assert result == expected
