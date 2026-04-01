"""
tests/test_build_llm_context.py — BuildLlmContextSkill ユニットテスト

LLM を使用しない純粋なコンテキスト組み立てロジックを検証する。
"""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _make_context_limits(tmp_path: Path) -> Path:
    """テスト用 context_limits.yaml を作成する。"""
    llm_dir = tmp_path / "llm"
    llm_dir.mkdir(parents=True)
    config = {
        "context_limits": {
            "qwen3.5:4b": {
                "max_context": 8192,
                "reserved_for_output": 2000,
                "available_for_input": 6192,
                "sections": {
                    "system_prompt": {"max": 1200, "priority": 1, "compress": False},
                    "current_state": {"max": 300, "priority": 2, "compress": False},
                    "recalled_memories": {"max": 1500, "priority": 3, "compress": True},
                    "available_skills": {"max": 1500, "priority": 4, "compress": True},
                    "persona": {"max": 500, "priority": 5, "compress": True},
                    "extra": {"max": 1192, "priority": 6, "compress": True},
                },
            }
        }
    }
    (llm_dir / "context_limits.yaml").write_text(yaml.dump(config))
    return tmp_path


def _make_working_memory_summary() -> dict:
    """テスト用 WorkingMemory サマリを返す。"""
    return {
        "current_goal": "GitHub トレンドを収集する",
        "active_character": "zephyr",
        "cycle_count": 3,
        "current_step_index": 1,
        "has_pending_plan": True,
        "plan_steps": [
            {"skill": "browse_source", "order": 0, "done": True, "expected_outcome": "収集完了"},
            {"skill": "store_episodic", "order": 1, "done": False, "expected_outcome": "記憶保存"},
        ],
        "recent_traces": [
            {"trace_id": "abc", "skill_name": "browse_source", "status": "success", "duration_ms": 1200},
        ],
        "recalled_memories_count": 2,
        "last_updated_at": "2026-04-01T00:00:00+00:00",
    }


class TestBuildLlmContextSkill:
    """BuildLlmContextSkill の動作検証"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.reasoning.build_llm_context import BuildLlmContextSkill
        assert BuildLlmContextSkill is not None

    @pytest.mark.asyncio
    async def test_basic_output_structure(self, tmp_path: Path):
        """基本的な出力構造を検証する"""
        from skills.reasoning.build_llm_context import BuildLlmContextSkill

        config_dir = _make_context_limits(tmp_path)
        skill = BuildLlmContextSkill(config_dir=config_dir)

        result = await skill.run({
            "target_skill": "store_episodic",
            "working_memory": _make_working_memory_summary(),
        })

        assert "messages" in result
        assert "token_estimate" in result
        assert "sections_used" in result
        assert "truncated_sections" in result
        assert isinstance(result["messages"], list)
        assert isinstance(result["token_estimate"], int)
        assert isinstance(result["sections_used"], list)
        assert isinstance(result["truncated_sections"], list)

    @pytest.mark.asyncio
    async def test_messages_contains_system_and_user(self, tmp_path: Path):
        """messages 配列に system と user ロールが含まれる"""
        from skills.reasoning.build_llm_context import BuildLlmContextSkill

        config_dir = _make_context_limits(tmp_path)
        skill = BuildLlmContextSkill(config_dir=config_dir)

        result = await skill.run({
            "target_skill": "store_episodic",
            "working_memory": _make_working_memory_summary(),
        })

        roles = [m["role"] for m in result["messages"]]
        assert "system" in roles
        assert "user" in roles

    @pytest.mark.asyncio
    async def test_system_message_contains_goal(self, tmp_path: Path):
        """system メッセージに現在の目標が含まれる"""
        from skills.reasoning.build_llm_context import BuildLlmContextSkill

        config_dir = _make_context_limits(tmp_path)
        skill = BuildLlmContextSkill(config_dir=config_dir)

        result = await skill.run({
            "target_skill": "store_episodic",
            "working_memory": _make_working_memory_summary(),
        })

        system_msgs = [m for m in result["messages"] if m["role"] == "system"]
        assert len(system_msgs) > 0
        system_content = system_msgs[0]["content"]
        assert "GitHub トレンドを収集する" in system_content

    @pytest.mark.asyncio
    async def test_system_message_contains_cycle_count(self, tmp_path: Path):
        """system メッセージにサイクル数が含まれる"""
        from skills.reasoning.build_llm_context import BuildLlmContextSkill

        config_dir = _make_context_limits(tmp_path)
        skill = BuildLlmContextSkill(config_dir=config_dir)

        result = await skill.run({
            "target_skill": "store_episodic",
            "working_memory": _make_working_memory_summary(),
        })

        system_msgs = [m for m in result["messages"] if m["role"] == "system"]
        system_content = system_msgs[0]["content"]
        assert "3" in system_content  # cycle_count

    @pytest.mark.asyncio
    async def test_user_message_contains_target_skill(self, tmp_path: Path):
        """user メッセージに target_skill が含まれる"""
        from skills.reasoning.build_llm_context import BuildLlmContextSkill

        config_dir = _make_context_limits(tmp_path)
        skill = BuildLlmContextSkill(config_dir=config_dir)

        result = await skill.run({
            "target_skill": "store_episodic",
            "working_memory": _make_working_memory_summary(),
        })

        user_msgs = [m for m in result["messages"] if m["role"] == "user"]
        assert len(user_msgs) > 0
        user_content = user_msgs[0]["content"]
        assert "store_episodic" in user_content

    @pytest.mark.asyncio
    async def test_recalled_memories_included_in_user_message(self, tmp_path: Path):
        """recalled_memories が user メッセージに含まれる（スコア順）"""
        from skills.reasoning.build_llm_context import BuildLlmContextSkill

        config_dir = _make_context_limits(tmp_path)
        skill = BuildLlmContextSkill(config_dir=config_dir)

        recalled = [
            {"content": "低スコア記憶", "score": 0.5},
            {"content": "高スコア記憶", "score": 0.9},
            {"content": "中スコア記憶", "score": 0.7},
        ]

        result = await skill.run({
            "target_skill": "store_episodic",
            "working_memory": _make_working_memory_summary(),
            "recalled_memories": recalled,
        })

        user_msgs = [m for m in result["messages"] if m["role"] == "user"]
        user_content = user_msgs[0]["content"]
        assert "高スコア記憶" in user_content
        # 高スコアが低スコアより先に登場する
        assert user_content.index("高スコア記憶") < user_content.index("低スコア記憶")

    @pytest.mark.asyncio
    async def test_persona_context_included_when_provided(self, tmp_path: Path):
        """persona_context が提供された場合は system メッセージに含まれる"""
        from skills.reasoning.build_llm_context import BuildLlmContextSkill

        config_dir = _make_context_limits(tmp_path)
        skill = BuildLlmContextSkill(config_dir=config_dir)

        persona = {"persona_prompt": "あなたは Zephyr という AI です。好奇心旺盛に振る舞ってください。"}

        result = await skill.run({
            "target_skill": "store_episodic",
            "working_memory": _make_working_memory_summary(),
            "persona_context": persona,
        })

        system_msgs = [m for m in result["messages"] if m["role"] == "system"]
        system_content = system_msgs[0]["content"]
        assert "Zephyr" in system_content

    @pytest.mark.asyncio
    async def test_no_persona_context_when_not_provided(self, tmp_path: Path):
        """persona_context が省略された場合はペルソナ情報なし"""
        from skills.reasoning.build_llm_context import BuildLlmContextSkill

        config_dir = _make_context_limits(tmp_path)
        skill = BuildLlmContextSkill(config_dir=config_dir)

        result = await skill.run({
            "target_skill": "store_episodic",
            "working_memory": _make_working_memory_summary(),
        })

        # persona セクションは sections_used に含まれないはず
        assert "persona" not in result["sections_used"]

    @pytest.mark.asyncio
    async def test_empty_recalled_memories_by_default(self, tmp_path: Path):
        """recalled_memories が省略された場合は空リスト扱い"""
        from skills.reasoning.build_llm_context import BuildLlmContextSkill

        config_dir = _make_context_limits(tmp_path)
        skill = BuildLlmContextSkill(config_dir=config_dir)

        result = await skill.run({
            "target_skill": "store_episodic",
            "working_memory": _make_working_memory_summary(),
        })

        # エラーなく実行できる
        assert isinstance(result["messages"], list)
        assert len(result["messages"]) >= 2

    @pytest.mark.asyncio
    async def test_token_estimate_is_positive(self, tmp_path: Path):
        """token_estimate は正の整数"""
        from skills.reasoning.build_llm_context import BuildLlmContextSkill

        config_dir = _make_context_limits(tmp_path)
        skill = BuildLlmContextSkill(config_dir=config_dir)

        result = await skill.run({
            "target_skill": "store_episodic",
            "working_memory": _make_working_memory_summary(),
        })

        assert result["token_estimate"] > 0

    @pytest.mark.asyncio
    async def test_truncation_when_max_tokens_exceeded(self, tmp_path: Path):
        """max_tokens が小さい場合にセクションが削減される"""
        from skills.reasoning.build_llm_context import BuildLlmContextSkill

        config_dir = _make_context_limits(tmp_path)
        skill = BuildLlmContextSkill(config_dir=config_dir)

        # 非常に小さいトークン上限を設定
        large_recalled = [
            {"content": "記憶" * 200, "score": 0.5 + i * 0.01}
            for i in range(20)
        ]

        result = await skill.run({
            "target_skill": "store_episodic",
            "working_memory": _make_working_memory_summary(),
            "recalled_memories": large_recalled,
            "max_tokens": 100,
        })

        # truncated_sections に何かが入っているか、sections_used が制限されている
        total_content = " ".join(m["content"] for m in result["messages"])
        # token_estimate は max_tokens 以下またはそれに近い値になる
        assert result["token_estimate"] <= 200  # max_tokens よりやや多くても許容

    @pytest.mark.asyncio
    async def test_sections_used_contains_current_state(self, tmp_path: Path):
        """sections_used に current_state が含まれる"""
        from skills.reasoning.build_llm_context import BuildLlmContextSkill

        config_dir = _make_context_limits(tmp_path)
        skill = BuildLlmContextSkill(config_dir=config_dir)

        result = await skill.run({
            "target_skill": "store_episodic",
            "working_memory": _make_working_memory_summary(),
        })

        assert "current_state" in result["sections_used"]

    @pytest.mark.asyncio
    async def test_available_skills_in_system_message(self, tmp_path: Path):
        """available_skills が working_memory に含まれる場合、system メッセージに反映される"""
        from skills.reasoning.build_llm_context import BuildLlmContextSkill

        config_dir = _make_context_limits(tmp_path)
        skill = BuildLlmContextSkill(config_dir=config_dir)

        wm_summary = _make_working_memory_summary()
        wm_summary["available_skills"] = ["browse_source", "store_episodic", "recall_related"]

        result = await skill.run({
            "target_skill": "store_episodic",
            "working_memory": wm_summary,
        })

        system_msgs = [m for m in result["messages"] if m["role"] == "system"]
        system_content = system_msgs[0]["content"]
        assert "browse_source" in system_content

    @pytest.mark.asyncio
    async def test_config_dir_default_fallback(self):
        """config_dir 省略時はデフォルト値が使用される（エラーなく動作）"""
        from skills.reasoning.build_llm_context import BuildLlmContextSkill

        skill = BuildLlmContextSkill()

        result = await skill.run({
            "target_skill": "store_episodic",
            "working_memory": _make_working_memory_summary(),
        })

        assert "messages" in result
        assert len(result["messages"]) >= 2
