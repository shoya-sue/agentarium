"""
tests/test_working_memory.py — WorkingMemory ユニットテスト

イミュータブル更新パターン・プラン管理・サマリ生成を検証する。
"""

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestPlanStepImport:
    """PlanStep / WorkingMemory のインポートを検証"""

    def test_import_plan_step(self):
        """PlanStep が正常にインポートできる"""
        from core.working_memory import PlanStep
        assert PlanStep is not None

    def test_import_working_memory(self):
        """WorkingMemory が正常にインポートできる"""
        from core.working_memory import WorkingMemory
        assert WorkingMemory is not None


class TestPlanStepCreation:
    """PlanStep の生成と属性を検証"""

    def test_create_plan_step(self):
        """PlanStep を正しく生成できる"""
        from core.working_memory import PlanStep

        step = PlanStep(
            skill="browse_source",
            params={"source_id": "hn"},
            expected_outcome="HN 記事を取得する",
            order=0,
        )
        assert step.skill == "browse_source"
        assert step.params == {"source_id": "hn"}
        assert step.expected_outcome == "HN 記事を取得する"
        assert step.order == 0
        assert step.done is False

    def test_plan_step_done_flag(self):
        """done フラグを True で生成できる"""
        from core.working_memory import PlanStep

        step = PlanStep(
            skill="llm_call",
            params={},
            expected_outcome="要約を生成する",
            order=1,
            done=True,
        )
        assert step.done is True


class TestWorkingMemoryDefaults:
    """WorkingMemory のデフォルト値を検証"""

    def test_default_values(self):
        """初期値が正しく設定される"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        assert wm.current_goal is None
        assert wm.plan_steps == []
        assert wm.current_step_index == 0
        assert wm.recent_traces == []
        assert wm.recalled_memories == []
        assert wm.active_character == "zephyr"
        assert wm.cycle_count == 0
        assert wm.last_updated_at == ""

    def test_plan_steps_not_shared(self):
        """複数インスタンス間でリストが共有されない"""
        from core.working_memory import WorkingMemory

        wm1 = WorkingMemory()
        wm2 = WorkingMemory()
        # 別インスタンスの plan_steps は独立している
        assert wm1.plan_steps is not wm2.plan_steps


class TestWorkingMemoryImmutableUpdates:
    """with_* メソッドのイミュータブル更新を検証"""

    def test_with_goal_returns_new_instance(self):
        """with_goal は新インスタンスを返し、元を変更しない"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        updated = wm.with_goal("情報収集を行う")

        assert updated is not wm
        assert updated.current_goal == "情報収集を行う"
        assert wm.current_goal is None  # 元は変更されない

    def test_with_goal_updates_timestamp(self):
        """with_goal は last_updated_at を更新する"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        updated = wm.with_goal("テスト目標")

        assert updated.last_updated_at != ""

    def test_with_plan_returns_new_instance(self):
        """with_plan は新インスタンスを返す"""
        from core.working_memory import WorkingMemory, PlanStep

        wm = WorkingMemory()
        steps = [
            PlanStep(skill="browse_source", params={}, expected_outcome="取得", order=0),
            PlanStep(skill="llm_call", params={}, expected_outcome="要約", order=1),
        ]
        updated = wm.with_plan(steps)

        assert updated is not wm
        assert len(updated.plan_steps) == 2
        assert len(wm.plan_steps) == 0  # 元は変更されない

    def test_with_plan_resets_step_index(self):
        """with_plan は current_step_index を 0 にリセットする"""
        from core.working_memory import WorkingMemory, PlanStep

        wm = WorkingMemory(current_step_index=3)
        steps = [PlanStep(skill="browse_source", params={}, expected_outcome="取得", order=0)]
        updated = wm.with_plan(steps)

        assert updated.current_step_index == 0

    def test_with_trace_appends_trace(self):
        """with_trace はトレースを追加した新インスタンスを返す"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        trace = {"trace_id": "abc", "skill_name": "browse_source", "status": "success"}
        updated = wm.with_trace(trace)

        assert updated is not wm
        assert len(updated.recent_traces) == 1
        assert updated.recent_traces[0] == trace
        assert len(wm.recent_traces) == 0

    def test_with_trace_respects_max_traces(self):
        """with_trace は max_traces を超えた古いトレースを除去する"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        # max_traces=3 で 4 件追加
        for i in range(4):
            trace = {"trace_id": str(i), "skill_name": "test"}
            wm = wm.with_trace(trace, max_traces=3)

        assert len(wm.recent_traces) == 3
        # 最古の trace_id="0" が除去され、残るのは 1, 2, 3
        ids = [t["trace_id"] for t in wm.recent_traces]
        assert "0" not in ids
        assert "3" in ids

    def test_with_trace_default_max_20(self):
        """with_trace のデフォルト max_traces は 20"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        for i in range(25):
            trace = {"trace_id": str(i)}
            wm = wm.with_trace(trace)

        assert len(wm.recent_traces) == 20

    def test_with_step_done_increments_index(self):
        """with_step_done は current_step_index を +1 する"""
        from core.working_memory import WorkingMemory, PlanStep

        steps = [
            PlanStep(skill="step0", params={}, expected_outcome="0", order=0),
            PlanStep(skill="step1", params={}, expected_outcome="1", order=1),
        ]
        wm = WorkingMemory(plan_steps=steps, current_step_index=0)
        updated = wm.with_step_done()

        assert updated is not wm
        assert updated.current_step_index == 1
        assert updated.plan_steps[0].done is True

    def test_with_step_done_marks_current_step(self):
        """with_step_done は現在ステップの done フラグを True にする"""
        from core.working_memory import WorkingMemory, PlanStep

        steps = [
            PlanStep(skill="step0", params={}, expected_outcome="0", order=0),
            PlanStep(skill="step1", params={}, expected_outcome="1", order=1),
        ]
        wm = WorkingMemory(plan_steps=steps, current_step_index=0)
        updated = wm.with_step_done()

        # 元の plan_steps は変更されない
        assert wm.plan_steps[0].done is False
        # 新インスタンスでは done=True
        assert updated.plan_steps[0].done is True

    def test_with_recalled_returns_new_instance(self):
        """with_recalled は新インスタンスを返す"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        memories = [{"id": "mem1", "content": "テスト記憶"}]
        updated = wm.with_recalled(memories)

        assert updated is not wm
        assert len(updated.recalled_memories) == 1
        assert len(wm.recalled_memories) == 0

    def test_with_character_changes_active_character(self):
        """with_character はキャラクターを変更した新インスタンスを返す"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        updated = wm.with_character("prako")

        assert updated is not wm
        assert updated.active_character == "prako"
        assert wm.active_character == "zephyr"

    def test_with_cycle_increment(self):
        """with_cycle_increment は cycle_count を +1 した新インスタンスを返す"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory(cycle_count=5)
        updated = wm.with_cycle_increment()

        assert updated is not wm
        assert updated.cycle_count == 6
        assert wm.cycle_count == 5

    def test_with_clear_plan(self):
        """with_clear_plan は plan_steps と current_step_index をリセットする"""
        from core.working_memory import WorkingMemory, PlanStep

        steps = [PlanStep(skill="test", params={}, expected_outcome="x", order=0)]
        wm = WorkingMemory(plan_steps=steps, current_step_index=1)
        updated = wm.with_clear_plan()

        assert updated is not wm
        assert updated.plan_steps == []
        assert updated.current_step_index == 0
        # 元は変更されない
        assert len(wm.plan_steps) == 1


class TestWorkingMemoryUtilities:
    """WorkingMemory のユーティリティメソッドを検証"""

    def test_current_step_returns_first_undone(self):
        """current_step は done でない最初のステップを返す"""
        from core.working_memory import WorkingMemory, PlanStep

        steps = [
            PlanStep(skill="step0", params={}, expected_outcome="0", order=0, done=True),
            PlanStep(skill="step1", params={}, expected_outcome="1", order=1, done=False),
            PlanStep(skill="step2", params={}, expected_outcome="2", order=2, done=False),
        ]
        wm = WorkingMemory(plan_steps=steps)
        step = wm.current_step()

        assert step is not None
        assert step.skill == "step1"

    def test_current_step_returns_none_when_all_done(self):
        """全ステップ完了時は None を返す"""
        from core.working_memory import WorkingMemory, PlanStep

        steps = [
            PlanStep(skill="step0", params={}, expected_outcome="0", order=0, done=True),
        ]
        wm = WorkingMemory(plan_steps=steps)
        assert wm.current_step() is None

    def test_current_step_returns_none_when_empty(self):
        """ステップが空の時は None を返す"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        assert wm.current_step() is None

    def test_has_pending_plan_true(self):
        """未完了ステップがある場合は True"""
        from core.working_memory import WorkingMemory, PlanStep

        steps = [
            PlanStep(skill="step0", params={}, expected_outcome="0", order=0, done=False),
        ]
        wm = WorkingMemory(plan_steps=steps)
        assert wm.has_pending_plan() is True

    def test_has_pending_plan_false_when_all_done(self):
        """全ステップ完了時は False"""
        from core.working_memory import WorkingMemory, PlanStep

        steps = [
            PlanStep(skill="step0", params={}, expected_outcome="0", order=0, done=True),
        ]
        wm = WorkingMemory(plan_steps=steps)
        assert wm.has_pending_plan() is False

    def test_has_pending_plan_false_when_empty(self):
        """ステップが空の時は False"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        assert wm.has_pending_plan() is False

    def test_to_summary_dict_structure(self):
        """to_summary_dict の構造が正しい"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory(
            current_goal="テスト目標",
            active_character="zephyr",
            cycle_count=3,
        )
        summary = wm.to_summary_dict()

        assert isinstance(summary, dict)
        assert "current_goal" in summary
        assert "active_character" in summary
        assert "cycle_count" in summary
        assert "has_pending_plan" in summary

    def test_to_summary_dict_recent_traces_max_5(self):
        """to_summary_dict の recent_traces は直近 5 件のみ"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        for i in range(10):
            wm = wm.with_trace({"trace_id": str(i), "skill_name": "test", "status": "success"})

        summary = wm.to_summary_dict()
        assert len(summary["recent_traces"]) == 5

    def test_to_summary_dict_recent_traces_is_last_5(self):
        """to_summary_dict の recent_traces は最新の 5 件"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        for i in range(8):
            wm = wm.with_trace({"trace_id": str(i), "skill_name": "test", "status": "success"})

        summary = wm.to_summary_dict()
        trace_ids = [t["trace_id"] for t in summary["recent_traces"]]
        # 最新 5 件 (3,4,5,6,7) が含まれる
        assert "7" in trace_ids
        assert "3" in trace_ids
        assert "2" not in trace_ids

    def test_to_summary_dict_plan_steps_summary(self):
        """to_summary_dict の plan_steps はステップ概要リスト"""
        from core.working_memory import WorkingMemory, PlanStep

        steps = [
            PlanStep(skill="browse_source", params={}, expected_outcome="取得", order=0),
            PlanStep(skill="llm_call", params={}, expected_outcome="要約", order=1, done=True),
        ]
        wm = WorkingMemory(plan_steps=steps)
        summary = wm.to_summary_dict()

        assert "plan_steps" in summary
        assert len(summary["plan_steps"]) == 2


class TestWorkingMemoryEmotionalState:
    """WorkingMemory の感情状態管理メソッドを検証（D18）"""

    def test_emotional_states_default_empty(self):
        """初期値では emotional_states は空辞書"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        assert wm.emotional_states == {}

    def test_with_emotional_state_returns_new_instance(self):
        """with_emotional_state は新インスタンスを返す"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        state = {"curiosity": 0.7, "excitement": 0.5}
        updated = wm.with_emotional_state("zephyr", state)

        assert updated is not wm

    def test_with_emotional_state_stores_state(self):
        """with_emotional_state は指定キャラクターの感情状態を格納する"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        state = {"curiosity": 0.7, "excitement": 0.5}
        updated = wm.with_emotional_state("zephyr", state)

        assert updated.emotional_states["zephyr"] == state

    def test_with_emotional_state_does_not_mutate_original(self):
        """with_emotional_state は元インスタンスを変更しない"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        state = {"curiosity": 0.7}
        updated = wm.with_emotional_state("zephyr", state)

        assert "zephyr" not in wm.emotional_states

    def test_with_emotional_state_overwrites_existing(self):
        """with_emotional_state は既存の感情状態を上書きする"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        wm = wm.with_emotional_state("zephyr", {"curiosity": 0.5})
        updated = wm.with_emotional_state("zephyr", {"curiosity": 0.9, "excitement": 0.3})

        assert updated.emotional_states["zephyr"]["curiosity"] == 0.9
        assert "excitement" in updated.emotional_states["zephyr"]

    def test_with_emotional_state_multiple_characters(self):
        """複数キャラクターの感情状態を独立して保持できる"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        wm = wm.with_emotional_state("zephyr", {"curiosity": 0.7})
        wm = wm.with_emotional_state("lynx", {"focus": 0.8})

        assert wm.emotional_states["zephyr"]["curiosity"] == 0.7
        assert wm.emotional_states["lynx"]["focus"] == 0.8

    def test_get_emotional_state_returns_state(self):
        """get_emotional_state は格納済みの感情状態を返す"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        state = {"curiosity": 0.65}
        wm = wm.with_emotional_state("zephyr", state)

        result = wm.get_emotional_state("zephyr")
        assert result == state

    def test_get_emotional_state_returns_none_when_absent(self):
        """get_emotional_state は未ロード時に None を返す"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        assert wm.get_emotional_state("zephyr") is None

    def test_to_summary_dict_includes_emotional_states_loaded(self):
        """to_summary_dict に emotional_states_loaded が含まれる"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        wm = wm.with_emotional_state("zephyr", {"curiosity": 0.5})
        summary = wm.to_summary_dict()

        assert "emotional_states_loaded" in summary
        assert "zephyr" in summary["emotional_states_loaded"]

    def test_copy_preserves_emotional_states(self):
        """_copy は emotional_states を引き継ぐ"""
        from core.working_memory import WorkingMemory

        wm = WorkingMemory()
        wm = wm.with_emotional_state("zephyr", {"curiosity": 0.7})
        updated = wm.with_goal("別の目標")  # emotional_states を変更しない with_*

        assert updated.emotional_states["zephyr"]["curiosity"] == 0.7


class TestLoadEmotionalState:
    """load_emotional_state 関数を検証（D18）"""

    def test_load_existing_json(self, tmp_path):
        """既存の JSON ファイルから感情状態を読み込む"""
        from core.working_memory import load_emotional_state

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        state_file = state_dir / "emotional_state_zephyr.json"
        state_data = {"curiosity": 0.7, "excitement": 0.5}
        state_file.write_text(json.dumps(state_data))

        result = load_emotional_state("zephyr", state_dir)
        assert result == state_data

    def test_create_initial_file_from_yaml_defaults(self, tmp_path):
        """JSON 未存在時は YAML defaults から初期ファイルを生成して返す"""
        from core.working_memory import load_emotional_state

        state_dir = tmp_path / "state"
        characters_dir = tmp_path / "characters"
        characters_dir.mkdir()

        # キャラクター YAML を用意
        char_yaml = {
            "name": "zephyr",
            "emotional_state_defaults": {"curiosity": 0.65, "excitement": 0.5},
        }
        (characters_dir / "zephyr.yaml").write_text(yaml.dump(char_yaml))

        result = load_emotional_state("zephyr", state_dir, characters_dir)

        assert result == {"curiosity": 0.65, "excitement": 0.5}

    def test_initial_file_is_persisted(self, tmp_path):
        """初期化後、JSON ファイルが生成されていること"""
        from core.working_memory import load_emotional_state

        state_dir = tmp_path / "state"
        characters_dir = tmp_path / "characters"
        characters_dir.mkdir()

        char_yaml = {
            "name": "zephyr",
            "emotional_state_defaults": {"curiosity": 0.65},
        }
        (characters_dir / "zephyr.yaml").write_text(yaml.dump(char_yaml))

        load_emotional_state("zephyr", state_dir, characters_dir)

        state_file = state_dir / "emotional_state_zephyr.json"
        assert state_file.exists()
        loaded = json.loads(state_file.read_text())
        assert loaded == {"curiosity": 0.65}

    def test_raises_if_yaml_missing(self, tmp_path):
        """YAML ファイルが存在しない場合は ValueError を送出する"""
        from core.working_memory import load_emotional_state

        state_dir = tmp_path / "state"
        characters_dir = tmp_path / "characters"
        characters_dir.mkdir()

        with pytest.raises(ValueError, match="キャラクター YAML が見つかりません"):
            load_emotional_state("nonexistent", state_dir, characters_dir)

    def test_raises_if_yaml_has_no_defaults(self, tmp_path):
        """YAML に emotional_state_defaults がない場合は ValueError を送出する"""
        from core.working_memory import load_emotional_state

        state_dir = tmp_path / "state"
        characters_dir = tmp_path / "characters"
        characters_dir.mkdir()

        char_yaml = {"name": "zephyr"}  # emotional_state_defaults なし
        (characters_dir / "zephyr.yaml").write_text(yaml.dump(char_yaml))

        with pytest.raises(ValueError, match="emotional_state_defaults"):
            load_emotional_state("zephyr", state_dir, characters_dir)


class TestSaveEmotionalState:
    """save_emotional_state 関数を検証（D18）"""

    def test_save_creates_file(self, tmp_path):
        """save_emotional_state は JSON ファイルを作成する"""
        from core.working_memory import save_emotional_state

        state_dir = tmp_path / "state"
        state = {"curiosity": 0.8, "boredom": 0.2}

        save_emotional_state("zephyr", state, state_dir)

        state_file = state_dir / "emotional_state_zephyr.json"
        assert state_file.exists()

    def test_save_writes_correct_content(self, tmp_path):
        """save_emotional_state は正しい内容を書き込む"""
        from core.working_memory import save_emotional_state

        state_dir = tmp_path / "state"
        state = {"curiosity": 0.8, "excitement": 0.3}

        save_emotional_state("zephyr", state, state_dir)

        state_file = state_dir / "emotional_state_zephyr.json"
        loaded = json.loads(state_file.read_text(encoding="utf-8"))
        assert loaded == state

    def test_save_creates_state_dir_if_absent(self, tmp_path):
        """state_dir が存在しなくてもディレクトリを自動作成する"""
        from core.working_memory import save_emotional_state

        state_dir = tmp_path / "non" / "existent" / "dir"
        save_emotional_state("zephyr", {"curiosity": 0.5}, state_dir)

        assert state_dir.exists()

    def test_save_overwrites_existing_file(self, tmp_path):
        """既存ファイルを上書きする"""
        from core.working_memory import save_emotional_state

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        state_file = state_dir / "emotional_state_zephyr.json"
        state_file.write_text(json.dumps({"curiosity": 0.1}))

        save_emotional_state("zephyr", {"curiosity": 0.9}, state_dir)

        loaded = json.loads(state_file.read_text())
        assert loaded["curiosity"] == 0.9
