"""
data/traces/ ディレクトリを監視し、新規 .json ファイルを SSE でブロードキャストする
"""
import json
import logging
from pathlib import Path
from typing import Callable, Awaitable

from watchfiles import awatch

logger = logging.getLogger(__name__)


async def watch_traces(
    traces_dir: Path,
    broadcast_fn: Callable[[dict], Awaitable[None]],
) -> None:
    """data/traces/ を監視し、新規 .json ファイルを検知したら broadcast する"""
    # ディレクトリが存在しない場合は作成
    if not traces_dir.exists():
        traces_dir.mkdir(parents=True, exist_ok=True)

    logger.info("トレース監視開始: %s", traces_dir)
    async for changes in awatch(str(traces_dir)):
        for change_type, path_str in changes:
            path = Path(path_str)
            if path.suffix != ".json":
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                await broadcast_fn({"type": "new_trace", "data": data})
                logger.debug("新規トレース検知: %s", path.name)
            except Exception as exc:
                # ファイル読み込み失敗は無視（書き込み中の可能性あり）
                logger.debug("トレース読み込みスキップ: %s (%s)", path.name, exc)
