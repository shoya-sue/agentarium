"""
core/working_memory.py — 1 AgentLoop サイクルをまたぐ実行コンテキスト

Agent が1サイクル中に保持する作業記憶。
イミュータブルパターンで全更新メソッドは新インスタンスを返す。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    """現在時刻を ISO 8601 形式で返す。"""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PlanStep:
    """
    プラン内の1実行ステップを表す。

    Attributes:
        skill: 実行する Skill 名
        params: Skill に渡すパラメータ
        expected_outcome: 期待する結果の記述
        order: 実行順序（0 始まり）
        done: 完了フラグ
    """

    skill: str
    params: dict[str, Any]
    expected_outcome: str
    order: int
    done: bool = False


@dataclass
class WorkingMemory:
    """
    1 AgentLoop サイクルをまたぐ実行コンテキスト。

    全 with_* メソッドはイミュータブルパターンに従い、
    必ず新インスタンスを返す（元インスタンスは変更しない）。

    Attributes:
        current_goal: 現在の目標
        plan_steps: 実行計画のステップリスト
        current_step_index: 現在のステップインデックス
        recent_traces: 直近 N 件の SkillTrace dict
        recalled_memories: 記憶から想起した内容リスト
        active_character: 現在アクティブなキャラクター名
        cycle_count: AgentLoop のサイクル数
        last_updated_at: 最終更新日時（ISO 8601）
    """

    current_goal: str | None = None
    plan_steps: list[PlanStep] = field(default_factory=list)
    current_step_index: int = 0
    recent_traces: list[dict[str, Any]] = field(default_factory=list)
    recalled_memories: list[dict[str, Any]] = field(default_factory=list)
    active_character: str = "zephyr"
    cycle_count: int = 0
    last_updated_at: str = ""

    def with_goal(self, goal: str) -> "WorkingMemory":
        """目標を設定した新インスタンスを返す。"""
        return WorkingMemory(
            current_goal=goal,
            plan_steps=list(self.plan_steps),
            current_step_index=self.current_step_index,
            recent_traces=list(self.recent_traces),
            recalled_memories=list(self.recalled_memories),
            active_character=self.active_character,
            cycle_count=self.cycle_count,
            last_updated_at=_now_iso(),
        )

    def with_plan(self, steps: list[PlanStep]) -> "WorkingMemory":
        """
        実行計画を設定した新インスタンスを返す。
        current_step_index は 0 にリセットする。
        """
        return WorkingMemory(
            current_goal=self.current_goal,
            plan_steps=list(steps),
            current_step_index=0,
            recent_traces=list(self.recent_traces),
            recalled_memories=list(self.recalled_memories),
            active_character=self.active_character,
            cycle_count=self.cycle_count,
            last_updated_at=_now_iso(),
        )

    def with_trace(
        self, trace: dict[str, Any], max_traces: int = 20
    ) -> "WorkingMemory":
        """
        トレースを追加した新インスタンスを返す。

        max_traces を超えた場合は古いものを除去する。
        """
        new_traces = list(self.recent_traces) + [trace]
        if len(new_traces) > max_traces:
            new_traces = new_traces[-max_traces:]

        return WorkingMemory(
            current_goal=self.current_goal,
            plan_steps=list(self.plan_steps),
            current_step_index=self.current_step_index,
            recent_traces=new_traces,
            recalled_memories=list(self.recalled_memories),
            active_character=self.active_character,
            cycle_count=self.cycle_count,
            last_updated_at=_now_iso(),
        )

    def with_step_done(self) -> "WorkingMemory":
        """
        現在ステップを完了済みにした新インスタンスを返す。

        current_step_index を +1 し、現在ステップの done フラグを True にする。
        """
        new_steps = []
        for i, step in enumerate(self.plan_steps):
            if i == self.current_step_index:
                # 完了ステップのコピーを作成（done=True）
                new_steps.append(
                    PlanStep(
                        skill=step.skill,
                        params=step.params,
                        expected_outcome=step.expected_outcome,
                        order=step.order,
                        done=True,
                    )
                )
            else:
                new_steps.append(step)

        return WorkingMemory(
            current_goal=self.current_goal,
            plan_steps=new_steps,
            current_step_index=self.current_step_index + 1,
            recent_traces=list(self.recent_traces),
            recalled_memories=list(self.recalled_memories),
            active_character=self.active_character,
            cycle_count=self.cycle_count,
            last_updated_at=_now_iso(),
        )

    def with_recalled(self, memories: list[dict[str, Any]]) -> "WorkingMemory":
        """想起した記憶を設定した新インスタンスを返す。"""
        return WorkingMemory(
            current_goal=self.current_goal,
            plan_steps=list(self.plan_steps),
            current_step_index=self.current_step_index,
            recent_traces=list(self.recent_traces),
            recalled_memories=list(memories),
            active_character=self.active_character,
            cycle_count=self.cycle_count,
            last_updated_at=_now_iso(),
        )

    def with_character(self, name: str) -> "WorkingMemory":
        """アクティブキャラクターを変更した新インスタンスを返す。"""
        return WorkingMemory(
            current_goal=self.current_goal,
            plan_steps=list(self.plan_steps),
            current_step_index=self.current_step_index,
            recent_traces=list(self.recent_traces),
            recalled_memories=list(self.recalled_memories),
            active_character=name,
            cycle_count=self.cycle_count,
            last_updated_at=_now_iso(),
        )

    def with_cycle_increment(self) -> "WorkingMemory":
        """cycle_count を +1 した新インスタンスを返す。"""
        return WorkingMemory(
            current_goal=self.current_goal,
            plan_steps=list(self.plan_steps),
            current_step_index=self.current_step_index,
            recent_traces=list(self.recent_traces),
            recalled_memories=list(self.recalled_memories),
            active_character=self.active_character,
            cycle_count=self.cycle_count + 1,
            last_updated_at=_now_iso(),
        )

    def with_clear_plan(self) -> "WorkingMemory":
        """
        実行計画をリセットした新インスタンスを返す。

        plan_steps を空にし、current_step_index を 0 にリセットする。
        """
        return WorkingMemory(
            current_goal=self.current_goal,
            plan_steps=[],
            current_step_index=0,
            recent_traces=list(self.recent_traces),
            recalled_memories=list(self.recalled_memories),
            active_character=self.active_character,
            cycle_count=self.cycle_count,
            last_updated_at=_now_iso(),
        )

    # ------------------------------------------------------------------
    # ユーティリティ
    # ------------------------------------------------------------------

    def current_step(self) -> PlanStep | None:
        """
        現在実行すべきステップを返す。

        done フラグが False のステップのうち、最初のものを返す。
        該当ステップがない場合は None を返す。
        """
        for step in self.plan_steps:
            if not step.done:
                return step
        return None

    def has_pending_plan(self) -> bool:
        """未完了のステップが存在するかを返す。"""
        return any(not step.done for step in self.plan_steps)

    def to_summary_dict(self) -> dict[str, Any]:
        """
        LLM に渡すサマリ辞書を返す。

        recent_traces は直近 5 件のサマリのみ含む。
        """
        # 直近 5 件のトレースサマリ（軽量化のため主要フィールドのみ）
        trace_summary_keys = ("trace_id", "skill_name", "status", "duration_ms", "error")
        recent_5 = self.recent_traces[-5:] if self.recent_traces else []
        trace_summaries = [
            {k: t.get(k) for k in trace_summary_keys if k in t}
            for t in recent_5
        ]

        # ステップ概要リスト
        plan_summary = [
            {
                "skill": s.skill,
                "order": s.order,
                "done": s.done,
                "expected_outcome": s.expected_outcome,
            }
            for s in self.plan_steps
        ]

        return {
            "current_goal": self.current_goal,
            "active_character": self.active_character,
            "cycle_count": self.cycle_count,
            "current_step_index": self.current_step_index,
            "has_pending_plan": self.has_pending_plan(),
            "plan_steps": plan_summary,
            "recent_traces": trace_summaries,
            "recalled_memories_count": len(self.recalled_memories),
            "last_updated_at": self.last_updated_at,
        }
