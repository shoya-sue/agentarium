"""
tests/skills/reasoning/test_run_dialogue.py — RunDialogueSkill ユニットテスト

LLMClient をモックして対話オーケストレーションを検証する。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))


class TestRunDialogueSkill:
    """RunDialogueSkill のテスト"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.reasoning.run_dialogue import RunDialogueSkill
        assert RunDialogueSkill is not None

    def _make_skill(self, responses: list[str] | None = None):
        """モック LLM クライアントでスキルを作成する"""
        from skills.reasoning.run_dialogue import RunDialogueSkill

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "テスト応答"

        if responses:
            mock_responses = []
            for r in responses:
                mr = MagicMock()
                mr.content = r
                mock_responses.append(mr)
            mock_llm.generate = AsyncMock(side_effect=mock_responses)
        else:
            mock_llm.generate = AsyncMock(return_value=mock_response)

        return RunDialogueSkill(llm_client=mock_llm)

    @pytest.mark.asyncio
    async def test_run_returns_transcript(self):
        """run が transcript を含む結果を返す"""
        skill = self._make_skill(responses=[
            "AI はとても重要な技術です",   # turn 1 (zephyr)
            "しかし倫理的リスクもあります", # turn 2 (lynx)
            "そのリスクは管理可能です",     # turn 3 (zephyr)
            "根拠が不十分です",             # turn 4 (lynx)
            "まとめ: AI の倫理議論",        # summary
        ])

        result = await skill.run({
            "topic": "AIの倫理問題",
            "max_turns": 4,
        })

        assert result["topic"] == "AIの倫理問題"
        assert len(result["transcript"]) == 4
        assert "summary" in result
        assert "completed_at" in result

    @pytest.mark.asyncio
    async def test_transcript_alternates_agents(self):
        """transcript がエージェントを交互に切り替える"""
        skill = self._make_skill()

        result = await skill.run({
            "topic": "テストトピック",
            "max_turns": 4,
        })

        agents = [t["agent"] for t in result["transcript"]]
        assert agents[0] == "zephyr"
        assert agents[1] == "lynx"
        assert agents[2] == "zephyr"
        assert agents[3] == "lynx"

    @pytest.mark.asyncio
    async def test_initial_speaker_lynx(self):
        """initial_speaker=lynx の場合 Lynx から開始する"""
        skill = self._make_skill()

        result = await skill.run({
            "topic": "テスト",
            "max_turns": 2,
            "initial_speaker": "lynx",
        })

        agents = [t["agent"] for t in result["transcript"]]
        assert agents[0] == "lynx"
        assert agents[1] == "zephyr"

    @pytest.mark.asyncio
    async def test_turn_numbers_are_sequential(self):
        """ターン番号が 1 から順番に付与される"""
        skill = self._make_skill()

        result = await skill.run({
            "topic": "テスト",
            "max_turns": 3,
        })

        turns = [t["turn"] for t in result["transcript"]]
        assert turns == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_raises_on_empty_topic(self):
        """topic が空の場合は ValueError"""
        skill = self._make_skill()

        with pytest.raises(ValueError, match="topic"):
            await skill.run({"topic": ""})

    @pytest.mark.asyncio
    async def test_raises_on_invalid_max_turns(self):
        """max_turns が範囲外の場合は ValueError"""
        skill = self._make_skill()

        with pytest.raises(ValueError, match="max_turns"):
            await skill.run({"topic": "テスト", "max_turns": 0})

        with pytest.raises(ValueError, match="max_turns"):
            await skill.run({"topic": "テスト", "max_turns": 11})

    @pytest.mark.asyncio
    async def test_raises_on_invalid_initial_speaker(self):
        """initial_speaker が無効な場合は ValueError"""
        skill = self._make_skill()

        with pytest.raises(ValueError, match="initial_speaker"):
            await skill.run({"topic": "テスト", "initial_speaker": "invalid"})

    @pytest.mark.asyncio
    async def test_llm_failure_does_not_stop_dialogue(self):
        """LLM エラーが発生しても対話が継続する（エラーメッセージが transcript に記録される）"""
        from skills.reasoning.run_dialogue import RunDialogueSkill

        mock_llm = MagicMock()
        call_count = [0]

        async def flaky_generate(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("LLM タイムアウト")
            mr = MagicMock()
            mr.content = "正常応答"
            return mr

        mock_llm.generate = AsyncMock(side_effect=flaky_generate)
        skill = RunDialogueSkill(llm_client=mock_llm)

        result = await skill.run({"topic": "テスト", "max_turns": 3})

        assert len(result["transcript"]) == 3
        # エラーターンはエラーメッセージが記録される
        error_turn = result["transcript"][1]
        assert "失敗" in error_turn["content"] or "エラー" in error_turn["content"].lower() or "LLM" in error_turn["content"]

    @pytest.mark.asyncio
    async def test_with_context(self):
        """context パラメータが対話に含まれる"""
        skill = self._make_skill()

        result = await skill.run({
            "topic": "機械学習の未来",
            "max_turns": 2,
            "context": "最新の GPT-4 論文に基づいて議論する",
        })

        assert len(result["transcript"]) == 2
