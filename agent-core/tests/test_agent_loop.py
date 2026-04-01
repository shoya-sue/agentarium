"""
tests/test_agent_loop.py — AgentLoop ユニットテスト

AgentLoop の内部 Skill 呼び出しをすべてモック化し、
外部依存なしでユニットテストを実行する。

非同期テストは asyncio.run() を使って同期的に実行する。
（pytest-asyncio が利用できない環境への対応）
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest
import yaml

# パスを通す
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ------------------------------------------------------------------
# ヘルパー関数
# ------------------------------------------------------------------


def _make_skill_registry(
    persona_result: Optional[dict] = None,
    recall_result: Optional[list] = None,
    select_result: Optional[dict] = None,
    evaluate_result: Optional[dict] = None,
    store_episodic_result: Optional[dict] = None,
    reflect_result: Optional[dict] = None,
) -> dict:
    """
    AgentLoop の skill_registry をモックで構築するヘルパー。

    デフォルト値は IDLE を選択する状態を想定する。
    """
    return {
        "build_persona_context": AsyncMock(
            return_value=persona_result
            or {
                "persona_prompt": "テストペルソナ",
                "character_name": "test_agent",
                "style_instructions": "",
                "motivation_context": None,
                "token_count": 10,
            }
        ),
        "recall_related": AsyncMock(return_value=recall_result or []),
        "select_skill": AsyncMock(
            return_value=select_result
            or {
                "selected_skill": "IDLE",
                "params": {},
                "reasoning": "テスト: IDLE",
                "confidence": 1.0,
            }
        ),
        "evaluate_importance": AsyncMock(
            return_value=evaluate_result
            or {
                "importance_score": 0.3,
                "reasoning": "テスト評価",
                "topics": [],
                "should_store": False,
            }
        ),
        "store_episodic": AsyncMock(return_value=store_episodic_result or {"stored": True}),
        "reflect": AsyncMock(
            return_value=reflect_result
            or {
                "cycle_summary": "テスト振り返り",
                "achievements": [],
                "failures": [],
                "key_learnings": [],
                "next_cycle_suggestions": [],
                "self_evaluation_score": 0.7,
                "model_used": "test_model",
            }
        ),
        "fetch_hacker_news": AsyncMock(return_value=[]),
    }


def _make_safety_config_dir(tmp_path: Path) -> Path:
    """テスト用 safety.yaml を含む config ディレクトリを作成する。"""
    safety_content = {
        "circuit_breaker": {"failure_threshold": 5, "recovery_timeout": 300},
        "skill_limits": {},
    }
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "safety.yaml").write_text(yaml.dump(safety_content))
    return tmp_path


# ------------------------------------------------------------------
# テストクラス
# ------------------------------------------------------------------


class TestAgentLoopImport:
    """インポート確認"""

    def test_import(self):
        """AgentLoop が正常にインポートできる"""
        from scheduler.agent_loop import AgentLoop

        assert AgentLoop is not None


class TestAgentLoopInitialState:
    """初期状態の確認"""

    def test_initial_state(self, tmp_path: Path):
        """初期状態: _running=False, _cycle_count=0"""
        from scheduler.agent_loop import AgentLoop

        config_dir = _make_safety_config_dir(tmp_path)
        loop = AgentLoop(
            character_name="test_agent",
            config_dir=config_dir,
        )
        assert loop.is_running is False
        assert loop.cycle_count == 0

    def test_stop_sets_running_false(self, tmp_path: Path):
        """stop() 後 is_running=False になる"""
        from scheduler.agent_loop import AgentLoop

        config_dir = _make_safety_config_dir(tmp_path)
        loop = AgentLoop(
            character_name="test_agent",
            config_dir=config_dir,
        )
        loop._running = True  # 直接セット（テスト用）
        asyncio.run(loop.stop())
        assert loop.is_running is False


class TestAgentLoopCycleCount:
    """サイクルカウントの検証"""

    def test_single_cycle_increments_count(self, tmp_path: Path):
        """1サイクル実行 → cycle_count == 1"""
        from scheduler.agent_loop import AgentLoop

        config_dir = _make_safety_config_dir(tmp_path)
        registry = _make_skill_registry()
        loop = AgentLoop(
            character_name="test_agent",
            max_cycles=1,
            cycle_interval_seconds=0,
            config_dir=config_dir,
            skill_registry=registry,
        )
        asyncio.run(loop.start())
        assert loop.cycle_count == 1

    def test_max_cycles_stops_loop(self, tmp_path: Path):
        """max_cycles=2 → 2サイクルで停止する"""
        from scheduler.agent_loop import AgentLoop

        config_dir = _make_safety_config_dir(tmp_path)
        registry = _make_skill_registry()
        loop = AgentLoop(
            character_name="test_agent",
            max_cycles=2,
            cycle_interval_seconds=0,
            config_dir=config_dir,
            skill_registry=registry,
        )
        asyncio.run(loop.start())
        assert loop.cycle_count == 2
        assert loop.is_running is False


class TestAgentLoopIdleSkip:
    """IDLE Skill の場合は追加 Skill を実行しない"""

    def test_idle_skill_skips_execution(self, tmp_path: Path):
        """select_skill が IDLE を返す → fetch_hacker_news などは呼ばれない"""
        from scheduler.agent_loop import AgentLoop

        config_dir = _make_safety_config_dir(tmp_path)
        registry = _make_skill_registry(
            select_result={
                "selected_skill": "IDLE",
                "params": {},
                "reasoning": "テスト: IDLE",
                "confidence": 1.0,
            }
        )
        loop = AgentLoop(
            character_name="test_agent",
            max_cycles=1,
            cycle_interval_seconds=0,
            config_dir=config_dir,
            skill_registry=registry,
        )
        asyncio.run(loop.start())

        # fetch_hacker_news は呼ばれていない
        registry["fetch_hacker_news"].assert_not_called()
        # evaluate_importance も呼ばれていない
        registry["evaluate_importance"].assert_not_called()


class TestAgentLoopSafetyBlock:
    """SafetyGuard が不許可の場合は Skill 実行をスキップ"""

    def test_safety_blocked_skill_skipped(self, tmp_path: Path):
        """SafetyGuard が不許可 → Skill 実行なし"""
        from scheduler.agent_loop import AgentLoop
        from core.safety_guard import SafetyResult

        config_dir = _make_safety_config_dir(tmp_path)
        # fetch_hacker_news を選択するが Safety に弾かれる
        registry = _make_skill_registry(
            select_result={
                "selected_skill": "fetch_hacker_news",
                "params": {},
                "reasoning": "テスト: fetch",
                "confidence": 0.9,
            }
        )
        loop = AgentLoop(
            character_name="test_agent",
            max_cycles=1,
            cycle_interval_seconds=0,
            config_dir=config_dir,
            skill_registry=registry,
        )

        # SafetyGuard.check が不許可を返すようにモック
        with patch.object(
            loop._safety,
            "check",
            return_value=SafetyResult(
                allowed=False,
                reason="テスト: 拒否",
                wait_seconds=60,
            ),
        ):
            asyncio.run(loop.start())

        # fetch_hacker_news は呼ばれていない
        registry["fetch_hacker_news"].assert_not_called()


class TestAgentLoopErrorHandling:
    """エラーハンドリングの検証"""

    def test_cycle_error_continues_loop(self, tmp_path: Path):
        """select_skill で例外 → ループは継続して max_cycles まで達する"""
        from scheduler.agent_loop import AgentLoop

        config_dir = _make_safety_config_dir(tmp_path)
        call_count = 0

        async def flaky_select_skill(params: dict) -> dict:
            """1回目は例外、2回目は IDLE を返す"""
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("テスト: select_skill 一時エラー")
            return {
                "selected_skill": "IDLE",
                "params": {},
                "reasoning": "テスト: 2回目は IDLE",
                "confidence": 1.0,
            }

        registry = _make_skill_registry()
        registry["select_skill"] = flaky_select_skill

        loop = AgentLoop(
            character_name="test_agent",
            max_cycles=2,
            cycle_interval_seconds=0,
            config_dir=config_dir,
            skill_registry=registry,
        )
        asyncio.run(loop.start())

        # エラーがあっても2サイクル完了している
        assert loop.cycle_count == 2


class TestAgentLoopReflect:
    """振り返り Skill の呼び出し検証"""

    def test_reflect_called_every_5_cycles(self, tmp_path: Path):
        """5サイクル実行 → reflect が1回呼ばれる"""
        from scheduler.agent_loop import AgentLoop

        config_dir = _make_safety_config_dir(tmp_path)
        registry = _make_skill_registry()
        loop = AgentLoop(
            character_name="test_agent",
            max_cycles=5,
            cycle_interval_seconds=0,
            config_dir=config_dir,
            skill_registry=registry,
        )
        asyncio.run(loop.start())

        assert loop.cycle_count == 5
        # reflect は5サイクル目に1回呼ばれる
        registry["reflect"].assert_called_once()

    def test_reflect_not_called_before_5_cycles(self, tmp_path: Path):
        """4サイクルでは reflect は呼ばれない"""
        from scheduler.agent_loop import AgentLoop

        config_dir = _make_safety_config_dir(tmp_path)
        registry = _make_skill_registry()
        loop = AgentLoop(
            character_name="test_agent",
            max_cycles=4,
            cycle_interval_seconds=0,
            config_dir=config_dir,
            skill_registry=registry,
        )
        asyncio.run(loop.start())

        assert loop.cycle_count == 4
        registry["reflect"].assert_not_called()


class TestAgentLoopEpisodicStorage:
    """エピソード記憶保存の検証"""

    def test_should_store_triggers_episodic_storage(self, tmp_path: Path):
        """evaluate_importance が should_store=True → store_episodic が呼ばれる"""
        from scheduler.agent_loop import AgentLoop

        config_dir = _make_safety_config_dir(tmp_path)
        # fetch_hacker_news を選択させる
        registry = _make_skill_registry(
            select_result={
                "selected_skill": "fetch_hacker_news",
                "params": {},
                "reasoning": "テスト: fetch",
                "confidence": 0.9,
            },
            evaluate_result={
                "importance_score": 0.8,
                "reasoning": "重要なコンテンツ",
                "topics": ["AI"],
                "should_store": True,  # 保存フラグ ON
            },
        )
        loop = AgentLoop(
            character_name="test_agent",
            max_cycles=1,
            cycle_interval_seconds=0,
            config_dir=config_dir,
            skill_registry=registry,
        )
        asyncio.run(loop.start())

        # store_episodic が呼ばれていることを確認
        registry["store_episodic"].assert_called_once()

    def test_should_not_store_skips_episodic(self, tmp_path: Path):
        """evaluate_importance が should_store=False → store_episodic は呼ばれない"""
        from scheduler.agent_loop import AgentLoop

        config_dir = _make_safety_config_dir(tmp_path)
        registry = _make_skill_registry(
            select_result={
                "selected_skill": "fetch_hacker_news",
                "params": {},
                "reasoning": "テスト: fetch",
                "confidence": 0.9,
            },
            evaluate_result={
                "importance_score": 0.2,
                "reasoning": "重要でないコンテンツ",
                "topics": [],
                "should_store": False,  # 保存フラグ OFF
            },
        )
        loop = AgentLoop(
            character_name="test_agent",
            max_cycles=1,
            cycle_interval_seconds=0,
            config_dir=config_dir,
            skill_registry=registry,
        )
        asyncio.run(loop.start())

        # store_episodic は呼ばれていない
        registry["store_episodic"].assert_not_called()
