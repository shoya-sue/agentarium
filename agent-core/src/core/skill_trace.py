"""
core/skill_trace.py — Skill 実行トレース（観測可能性）

全 Skill 実行に SkillTrace を付与し、data/traces/ に JSON で保存する。
設計原則: 全 Skill 実行に SkillTrace 付与（CLAUDE.md 参照）
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TraceStatus(str, Enum):
    """Skill 実行状態"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"


@dataclass
class SkillTrace:
    """
    Skill 1 回の実行を記録するトレース。

    使用例::

        trace = SkillTrace.start("browse_source", {"source_id": "hacker_news"})
        try:
            result = await run_skill(...)
            trace.finish(result=result, result_count=len(result))
        except Exception as e:
            trace.fail(error=str(e))
        finally:
            trace.save(Path("data/traces"))
    """

    trace_id: str
    skill_name: str
    input_params: dict[str, Any]
    status: TraceStatus
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    result_count: int | None = None
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    # 内部計時用（保存時は含まない）
    _start_time: float = field(default_factory=time.monotonic, repr=False)

    @classmethod
    def start(
        cls,
        skill_name: str,
        input_params: dict[str, Any] | None = None,
    ) -> "SkillTrace":
        """実行開始時に SkillTrace を作成する"""
        return cls(
            trace_id=str(uuid.uuid4()),
            skill_name=skill_name,
            input_params=input_params or {},
            status=TraceStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            _start_time=time.monotonic(),
        )

    def finish(
        self,
        result: Any = None,
        result_count: int | None = None,
        **extra: Any,
    ) -> None:
        """Skill が成功で完了した時に呼ぶ"""
        elapsed = time.monotonic() - self._start_time
        self.status = TraceStatus.SUCCESS
        self.finished_at = datetime.now(timezone.utc)
        self.duration_ms = int(elapsed * 1000)
        self.result_count = result_count
        if extra:
            self.extra.update(extra)

    def fail(self, error: str, **extra: Any) -> None:
        """Skill が失敗した時に呼ぶ"""
        elapsed = time.monotonic() - self._start_time
        self.status = TraceStatus.FAILURE
        self.finished_at = datetime.now(timezone.utc)
        self.duration_ms = int(elapsed * 1000)
        self.error = error
        if extra:
            self.extra.update(extra)

    def to_dict(self) -> dict[str, Any]:
        """JSON 保存用の辞書に変換する"""
        return {
            "trace_id": self.trace_id,
            "skill_name": self.skill_name,
            "input_params": self.input_params,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_ms": self.duration_ms,
            "result_count": self.result_count,
            "error": self.error,
            "extra": self.extra,
        }

    def save(self, traces_dir: Path) -> Path:
        """
        data/traces/{YYYY-MM-DD}/{skill_name}/{trace_id}.json に保存する。

        Returns:
            保存先ファイルパス
        """
        date_str = self.started_at.strftime("%Y-%m-%d")
        out_dir = traces_dir / date_str / self.skill_name
        out_dir.mkdir(parents=True, exist_ok=True)

        out_path = out_dir / f"{self.trace_id}.json"
        out_path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.debug("トレース保存: %s", out_path)
        return out_path

    def log(self, log_fields: list[str] | None = None) -> None:
        """指定フィールドをログに出力する"""
        fields = log_fields or ["skill_name", "status", "duration_ms", "result_count", "error"]
        data = self.to_dict()
        parts = [f"{k}={data.get(k)!r}" for k in fields if k in data]
        logger.info("SkillTrace [%s] %s", self.skill_name, " ".join(parts))
