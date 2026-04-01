"""
core/working_memory.py — 1 AgentLoop サイクルをまたぐ実行コンテキスト

Agent が1サイクル中に保持する作業記憶。
イミュータブルパターンで全更新メソッドは新インスタンスを返す。

D18: 感情状態の永続化
  - インメモリ: WorkingMemory.emotional_states
  - 永続化: data/state/emotional_state_{character}.json
  - 初期化: ファイル未存在時は character YAML の emotional_state_defaults から生成
"""

from __future__ import annotations

import json
import logging
import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from utils.config import find_project_root

logger = logging.getLogger(__name__)


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
    # D18: 感情状態インメモリキャッシュ。キャラクター名 → {軸名: スコア}
    emotional_states: dict[str, dict[str, float]] = field(default_factory=dict)

    def _copy(self, **overrides: Any) -> "WorkingMemory":
        """全フィールドをコピーし、overrides で指定したフィールドのみ上書きした新インスタンスを返す。"""
        return WorkingMemory(
            current_goal=overrides.get("current_goal", self.current_goal),
            plan_steps=overrides.get("plan_steps", list(self.plan_steps)),
            current_step_index=overrides.get("current_step_index", self.current_step_index),
            recent_traces=overrides.get("recent_traces", list(self.recent_traces)),
            recalled_memories=overrides.get("recalled_memories", list(self.recalled_memories)),
            active_character=overrides.get("active_character", self.active_character),
            cycle_count=overrides.get("cycle_count", self.cycle_count),
            last_updated_at=overrides.get("last_updated_at", _now_iso()),
            emotional_states=overrides.get("emotional_states", dict(self.emotional_states)),
        )

    def with_goal(self, goal: str) -> "WorkingMemory":
        """目標を設定した新インスタンスを返す。"""
        return self._copy(current_goal=goal)

    def with_plan(self, steps: list[PlanStep]) -> "WorkingMemory":
        """
        実行計画を設定した新インスタンスを返す。
        current_step_index は 0 にリセットする。
        """
        return self._copy(plan_steps=list(steps), current_step_index=0)

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
        return self._copy(recent_traces=new_traces)

    def with_step_done(self) -> "WorkingMemory":
        """
        現在ステップを完了済みにした新インスタンスを返す。

        current_step_index を +1 し、現在ステップの done フラグを True にする。
        """
        new_steps = []
        for i, step in enumerate(self.plan_steps):
            if i == self.current_step_index:
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
        return self._copy(plan_steps=new_steps, current_step_index=self.current_step_index + 1)

    def with_recalled(self, memories: list[dict[str, Any]]) -> "WorkingMemory":
        """想起した記憶を設定した新インスタンスを返す。"""
        return self._copy(recalled_memories=list(memories))

    def with_character(self, name: str) -> "WorkingMemory":
        """アクティブキャラクターを変更した新インスタンスを返す。"""
        return self._copy(active_character=name)

    def with_cycle_increment(self) -> "WorkingMemory":
        """cycle_count を +1 した新インスタンスを返す。"""
        return self._copy(cycle_count=self.cycle_count + 1)

    def with_clear_plan(self) -> "WorkingMemory":
        """
        実行計画をリセットした新インスタンスを返す。

        plan_steps を空にし、current_step_index を 0 にリセットする。
        """
        return self._copy(plan_steps=[], current_step_index=0)

    def with_emotional_state(
        self, character_name: str, state: dict[str, float]
    ) -> "WorkingMemory":
        """
        指定キャラクターの感情状態を更新した新インスタンスを返す（D18）。

        Args:
            character_name: キャラクター名（例: 'zephyr'）
            state: 感情軸名 → スコア（0.0〜1.0）の辞書

        Returns:
            emotional_states[character_name] が更新された新 WorkingMemory
        """
        new_states = dict(self.emotional_states)
        new_states[character_name] = dict(state)
        return self._copy(emotional_states=new_states)

    def get_emotional_state(self, character_name: str) -> dict[str, float] | None:
        """
        指定キャラクターの感情状態を返す。未ロードの場合は None。
        """
        return self.emotional_states.get(character_name)

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
            "emotional_states_loaded": list(self.emotional_states.keys()),
            "last_updated_at": self.last_updated_at,
        }


# ------------------------------------------------------------------
# 感情状態ファイル I/O ユーティリティ（D18）
# ------------------------------------------------------------------

def load_emotional_state(
    character_name: str,
    state_dir: Path,
    characters_dir: Path | None = None,
) -> dict[str, float]:
    """
    感情状態を JSON ファイルから読み込む。ファイルが存在しない場合は
    キャラクター YAML の emotional_state_defaults から初期ファイルを生成して返す。

    Args:
        character_name: キャラクター名（例: 'zephyr'）
        state_dir: 感情状態 JSON を格納するディレクトリ（data/state/）
        characters_dir: キャラクター YAML のディレクトリ（初期化時にのみ使用）。
            None の場合はプロジェクトルートの config/characters/ を使用する。

    Returns:
        感情軸名 → スコア（0.0〜1.0）の辞書
    """
    state_path = state_dir / f"emotional_state_{character_name}.json"

    if state_path.exists():
        with state_path.open(encoding="utf-8") as f:
            state: dict[str, float] = json.load(f)
        logger.debug("感情状態を読み込み: character=%s path=%s", character_name, state_path)
        return state

    # ファイル未存在: character YAML の defaults から初期化
    if characters_dir is None:
        # Docker / ローカル両対応: config/characters/ を上位から探索
        characters_dir = find_project_root(Path(__file__).resolve().parent) / "config" / "characters"

    char_yaml_path = characters_dir / f"{character_name}.yaml"
    if not char_yaml_path.exists():
        raise ValueError(
            f"感情状態の初期化に失敗: キャラクター YAML が見つかりません: {char_yaml_path}"
        )

    with char_yaml_path.open(encoding="utf-8") as f:
        char_data = yaml.safe_load(f)

    defaults: dict[str, float] = char_data.get("emotional_state_defaults", {})
    if not defaults:
        raise ValueError(
            f"キャラクター '{character_name}' に emotional_state_defaults が定義されていません"
        )

    # 初期ファイルを生成
    state_dir.mkdir(parents=True, exist_ok=True)
    with state_path.open("w", encoding="utf-8") as f:
        json.dump(defaults, f, ensure_ascii=False, indent=2)

    logger.info(
        "感情状態を初期化: character=%s defaults=%s", character_name, list(defaults.keys())
    )
    return dict(defaults)


def save_emotional_state(
    character_name: str,
    state: dict[str, float],
    state_dir: Path,
) -> None:
    """
    感情状態を JSON ファイルに書き込む（即時永続化）。

    Args:
        character_name: キャラクター名（例: 'zephyr'）
        state: 感情軸名 → スコア（0.0〜1.0）の辞書
        state_dir: 感情状態 JSON を格納するディレクトリ（data/state/）
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / f"emotional_state_{character_name}.json"
    with state_path.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    logger.debug("感情状態を保存: character=%s path=%s", character_name, state_path)
