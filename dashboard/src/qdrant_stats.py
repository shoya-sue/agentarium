"""
Qdrant REST API からコレクション統計を取得する
"""
import logging

import httpx

logger = logging.getLogger(__name__)


async def get_qdrant_stats(qdrant_url: str) -> dict:
    """Qdrant REST API からコレクション統計を取得する

    Qdrant が起動していない場合でも 200 を返し、error フィールドにメッセージを入れる。
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.get(f"{qdrant_url}/collections")
            r.raise_for_status()
            collections = r.json().get("result", {}).get("collections", [])

            stats: dict[str, dict] = {}
            for col in collections:
                name = col["name"]
                try:
                    r2 = await client.get(f"{qdrant_url}/collections/{name}")
                    r2.raise_for_status()
                    info = r2.json().get("result", {})
                    stats[name] = {
                        "vectors_count": info.get("vectors_count", 0),
                        "points_count": info.get("points_count", 0),
                    }
                except Exception as inner_exc:
                    stats[name] = {"error": str(inner_exc)}

            return {"collections": stats}

        except Exception as exc:
            logger.warning("Qdrant 接続エラー: %s", exc)
            return {"error": str(exc), "collections": {}}
