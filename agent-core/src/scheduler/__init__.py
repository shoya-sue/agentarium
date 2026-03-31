"""
scheduler — ルールベース巡回スケジューラ（Phase 1）

PatrolScheduler: config/schedules/patrol.yaml に従い、
各情報ソースを定期的に巡回して browse_source Skill を呼び出す。

Phase 2 以降で LLM 駆動の Skill 選択に移行予定。
"""

from .patrol_scheduler import PatrolScheduler

__all__ = ["PatrolScheduler"]
