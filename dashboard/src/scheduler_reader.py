"""
スケジューラ状態の読み取り

優先順位:
  1. data/scheduler/states.json（PatrolScheduler が書き出すリアルタイム状態）
  2. config/schedules/patrol.yaml（フォールバック: 静的設定から初期状態を生成）
"""
import json
import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def read_scheduler_states(data_dir: Path, config_dir: Path) -> dict:
    """スケジューラの現在状態を返す"""
    states_file = data_dir / "scheduler" / "states.json"

    if states_file.exists():
        try:
            return json.loads(states_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("states.json 読み込み失敗、フォールバック使用: %s", exc)

    # フォールバック: patrol.yaml からダミー状態を生成
    patrol_yaml = config_dir / "schedules" / "patrol.yaml"
    if patrol_yaml.exists():
        try:
            cfg = yaml.safe_load(patrol_yaml.read_text(encoding="utf-8")) or {}
            sources = cfg.get("sources", [])
            return {
                "updated_at": None,
                "sources": [
                    {
                        "source_id": s.get("id", "unknown"),
                        "enabled": s.get("enabled", True),
                        "interval_min": s.get("interval_min", 60),
                        "last_run_at": None,
                        "consecutive_failures": 0,
                    }
                    for s in sources
                ],
            }
        except Exception as exc:
            logger.warning("patrol.yaml 読み込み失敗: %s", exc)

    return {"updated_at": None, "sources": []}
