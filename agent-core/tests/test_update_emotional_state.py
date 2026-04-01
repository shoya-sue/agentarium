"""
tests/test_update_emotional_state.py — UpdateEmotionalStateSkill ユニットテスト

LLM モックを使用して、感情デルタ適用・永続化・エラーハンドリングを検証する。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ---------------------------------------------------------------------------
# テスト用フィクスチャ
# ---------------------------------------------------------------------------


def _make_config_dir(tmp_path: Path) -> Path:
    """テスト用 config ディレクトリを tmp_path に作成して返す。"""
    config_dir = tmp_path / "config"
    (config_dir / "characters").mkdir(parents=True)
    (config_dir / "llm").mkdir(parents=True)

    zephyr_yaml = {
        "core_identity": {
            "name": "Zephyr",
            "personality_prose": "Zephyrは好奇心の塊。",
            "big_five": {
                "openness": 0.85,
                "conscientiousness": 0.70,
                "extraversion": 0.55,
                "agreeableness": 0.75,
                "neuroticism": 0.25,
            },
        },
        "emotional_axes": {
            "active": ["curiosity", "excitement", "boredom", "anxiety"],
        },
        "emotional_state_defaults": {
            "curiosity": 0.65,
            "excitement": 0.50,
            "boredom": 0.30,
            "anxiety": 0.20,
        },
    }
    (config_dir / "characters" / "zephyr.yaml").write_text(
        yaml.dump(zephyr_yaml, allow_unicode=True)
    )

    routing_yaml = {
        "default_model": "qwen3.5:35b-a3b",
        "skill_models": {"affect_mapping": "qwen3.5:4b"},
    }
    (config_dir / "llm" / "routing.yaml").write_text(yaml.dump(routing_yaml))

    return config_dir


@dataclass
class _MockResponse:
    """LLMResponse モック"""

    content: str
    model: str = "qwen3.5:4b"
    prompt_eval_count: int = 100
    eval_count: int = 50
    eval_duration_ns: int = 1_000_000_000

    def parse_json(self) -> Any:
        text = self.content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            inner = [l for l in lines[1:] if l.strip() != "```"]
            text = "\n".join(inner).strip()
        return json.loads(text)


def _make_llm_mock(response_json: list[dict[str, Any]]) -> Any:
    """指定したデルタ配列を返す LLM モックを作成する。"""
    content = "```json\n" + json.dumps(response_json, ensure_ascii=False) + "\n```"
    mock = MagicMock()
    mock.generate = AsyncMock(return_value=_MockResponse(content=content))
    return mock


# ---------------------------------------------------------------------------
# _apply_deltas のユニットテスト
# ---------------------------------------------------------------------------


class TestApplyDeltas:
    """_apply_deltas 関数を直接テスト"""

    def test_apply_positive_delta(self):
        """正のデルタを加算できる"""
        from skills.character.update_emotional_state import _apply_deltas

        current = {"curiosity": 0.5, "excitement": 0.5}
        deltas = [{"index": 0, "emotional_delta": {"curiosity": 0.2}}]
        updated, axes = _apply_deltas(current, deltas, ["curiosity", "excitement"])

        assert updated["curiosity"] == pytest.approx(0.7)
        assert updated["excitement"] == pytest.approx(0.5)
        assert "curiosity" in axes

    def test_apply_negative_delta(self):
        """負のデルタを減算できる"""
        from skills.character.update_emotional_state import _apply_deltas

        current = {"curiosity": 0.5}
        deltas = [{"index": 0, "emotional_delta": {"curiosity": -0.3}}]
        updated, axes = _apply_deltas(current, deltas, ["curiosity"])

        assert updated["curiosity"] == pytest.approx(0.2)

    def test_clamp_max(self):
        """スコアが 1.0 を超えないようにクランプされる"""
        from skills.character.update_emotional_state import _apply_deltas

        current = {"curiosity": 0.9}
        deltas = [{"index": 0, "emotional_delta": {"curiosity": 0.5}}]
        updated, _ = _apply_deltas(current, deltas, ["curiosity"])

        assert updated["curiosity"] == pytest.approx(1.0)

    def test_clamp_min(self):
        """スコアが 0.0 を下回らないようにクランプされる"""
        from skills.character.update_emotional_state import _apply_deltas

        current = {"anxiety": 0.1}
        deltas = [{"index": 0, "emotional_delta": {"anxiety": -0.5}}]
        updated, _ = _apply_deltas(current, deltas, ["anxiety"])

        assert updated["anxiety"] == pytest.approx(0.0)

    def test_inactive_axis_ignored(self):
        """active_axes に含まれない軸は無視される"""
        from skills.character.update_emotional_state import _apply_deltas

        current = {"curiosity": 0.5}
        deltas = [{"index": 0, "emotional_delta": {"nonexistent_axis": 0.9}}]
        updated, axes = _apply_deltas(current, deltas, ["curiosity"])

        assert "nonexistent_axis" not in updated
        assert axes == []

    def test_multiple_contents_cumulative(self):
        """複数コンテンツのデルタが累積して適用される"""
        from skills.character.update_emotional_state import _apply_deltas

        current = {"curiosity": 0.5}
        deltas = [
            {"index": 0, "emotional_delta": {"curiosity": 0.1}},
            {"index": 1, "emotional_delta": {"curiosity": 0.1}},
        ]
        updated, _ = _apply_deltas(current, deltas, ["curiosity"])

        assert updated["curiosity"] == pytest.approx(0.7)

    def test_empty_deltas_no_change(self):
        """デルタが空の場合はスコアが変化しない"""
        from skills.character.update_emotional_state import _apply_deltas

        current = {"curiosity": 0.5, "excitement": 0.4}
        updated, axes = _apply_deltas(current, [], ["curiosity", "excitement"])

        assert updated == current
        assert axes == []

    def test_axes_updated_sorted(self):
        """更新された軸名リストはソートされている"""
        from skills.character.update_emotional_state import _apply_deltas

        current = {"curiosity": 0.5, "excitement": 0.5, "boredom": 0.3}
        deltas = [{"index": 0, "emotional_delta": {"excitement": 0.1, "boredom": 0.1}}]
        _, axes = _apply_deltas(current, deltas, ["curiosity", "excitement", "boredom"])

        assert axes == sorted(axes)


# ---------------------------------------------------------------------------
# UpdateEmotionalStateSkill のユニットテスト
# ---------------------------------------------------------------------------


class TestUpdateEmotionalStateSkill:
    """UpdateEmotionalStateSkill の run メソッドを検証"""

    @pytest.mark.asyncio
    async def test_run_returns_required_keys(self, tmp_path):
        """run の戻り値に必要なキーが含まれる"""
        from skills.character.update_emotional_state import UpdateEmotionalStateSkill

        config_dir = _make_config_dir(tmp_path)
        state_dir = tmp_path / "state"
        llm_mock = _make_llm_mock([
            {"index": 0, "emotional_delta": {"curiosity": 0.1}},
        ])

        skill = UpdateEmotionalStateSkill(llm_mock, config_dir=config_dir)
        result = await skill.run({
            "character_name": "zephyr",
            "contents": [{"index": 0, "summary": "新しい LLM モデルが発表された"}],
            "state_dir": str(state_dir),
        })

        assert "character_name" in result
        assert "updated_state" in result
        assert "deltas_applied" in result
        assert "axes_updated" in result

    @pytest.mark.asyncio
    async def test_run_applies_delta_to_state(self, tmp_path):
        """run がデルタをスコアに加算する"""
        from skills.character.update_emotional_state import UpdateEmotionalStateSkill

        config_dir = _make_config_dir(tmp_path)
        state_dir = tmp_path / "state"
        # curiosity のデフォルト: 0.65 + 0.2 = 0.85
        llm_mock = _make_llm_mock([
            {"index": 0, "emotional_delta": {"curiosity": 0.2}},
        ])

        skill = UpdateEmotionalStateSkill(llm_mock, config_dir=config_dir)
        result = await skill.run({
            "character_name": "zephyr",
            "contents": [{"index": 0, "summary": "画期的な発見"}],
            "state_dir": str(state_dir),
        })

        assert result["updated_state"]["curiosity"] == pytest.approx(0.85)

    @pytest.mark.asyncio
    async def test_run_persists_state_to_file(self, tmp_path):
        """run が感情状態を JSON ファイルに永続化する"""
        from skills.character.update_emotional_state import UpdateEmotionalStateSkill

        config_dir = _make_config_dir(tmp_path)
        state_dir = tmp_path / "state"
        llm_mock = _make_llm_mock([
            {"index": 0, "emotional_delta": {"excitement": 0.3}},
        ])

        skill = UpdateEmotionalStateSkill(llm_mock, config_dir=config_dir)
        await skill.run({
            "character_name": "zephyr",
            "contents": [{"index": 0, "summary": "ワクワクするニュース"}],
            "state_dir": str(state_dir),
        })

        state_file = state_dir / "emotional_state_zephyr.json"
        assert state_file.exists()
        saved = json.loads(state_file.read_text())
        # excitement: 0.50 + 0.30 = 0.80
        assert saved["excitement"] == pytest.approx(0.80)

    @pytest.mark.asyncio
    async def test_run_uses_affect_model_from_routing(self, tmp_path):
        """routing.yaml の affect_mapping モデルを使用する"""
        from skills.character.update_emotional_state import UpdateEmotionalStateSkill

        config_dir = _make_config_dir(tmp_path)
        state_dir = tmp_path / "state"
        llm_mock = _make_llm_mock([])

        skill = UpdateEmotionalStateSkill(llm_mock, config_dir=config_dir)
        await skill.run({
            "character_name": "zephyr",
            "contents": [{"index": 0, "summary": "テスト"}],
            "state_dir": str(state_dir),
        })

        call_kwargs = llm_mock.generate.call_args
        assert call_kwargs.kwargs.get("model") == "qwen3.5:4b"

    @pytest.mark.asyncio
    async def test_run_respects_model_override(self, tmp_path):
        """params.model で使用モデルを上書きできる"""
        from skills.character.update_emotional_state import UpdateEmotionalStateSkill

        config_dir = _make_config_dir(tmp_path)
        state_dir = tmp_path / "state"
        llm_mock = _make_llm_mock([])

        skill = UpdateEmotionalStateSkill(llm_mock, config_dir=config_dir)
        await skill.run({
            "character_name": "zephyr",
            "contents": [{"index": 0, "summary": "テスト"}],
            "state_dir": str(state_dir),
            "model": "qwen3.5:14b",
        })

        call_kwargs = llm_mock.generate.call_args
        assert call_kwargs.kwargs.get("model") == "qwen3.5:14b"

    @pytest.mark.asyncio
    async def test_run_raises_on_empty_contents(self, tmp_path):
        """contents が空の場合は ValueError を送出する"""
        from skills.character.update_emotional_state import UpdateEmotionalStateSkill

        config_dir = _make_config_dir(tmp_path)
        llm_mock = _make_llm_mock([])

        skill = UpdateEmotionalStateSkill(llm_mock, config_dir=config_dir)
        with pytest.raises(ValueError, match="contents が空"):
            await skill.run({
                "character_name": "zephyr",
                "contents": [],
                "state_dir": str(tmp_path / "state"),
            })

    @pytest.mark.asyncio
    async def test_run_raises_on_invalid_json_response(self, tmp_path):
        """LLM が JSON でない出力を返した場合は ValueError を送出する"""
        from skills.character.update_emotional_state import UpdateEmotionalStateSkill

        config_dir = _make_config_dir(tmp_path)
        state_dir = tmp_path / "state"

        bad_mock = MagicMock()
        bad_mock.generate = AsyncMock(
            return_value=_MockResponse(content="これは JSON ではありません")
        )

        skill = UpdateEmotionalStateSkill(bad_mock, config_dir=config_dir)
        with pytest.raises(ValueError, match="JSON パース"):
            await skill.run({
                "character_name": "zephyr",
                "contents": [{"index": 0, "summary": "テスト"}],
                "state_dir": str(state_dir),
            })

    @pytest.mark.asyncio
    async def test_run_raises_if_character_yaml_missing(self, tmp_path):
        """存在しないキャラクターを指定すると ValueError を送出する"""
        from skills.character.update_emotional_state import UpdateEmotionalStateSkill

        config_dir = _make_config_dir(tmp_path)
        llm_mock = _make_llm_mock([])

        skill = UpdateEmotionalStateSkill(llm_mock, config_dir=config_dir)
        with pytest.raises(ValueError, match="キャラクター YAML が見つかりません"):
            await skill.run({
                "character_name": "nonexistent",
                "contents": [{"index": 0, "summary": "テスト"}],
                "state_dir": str(tmp_path / "state"),
            })

    @pytest.mark.asyncio
    async def test_run_returns_character_name(self, tmp_path):
        """run の戻り値にキャラクター名が含まれる"""
        from skills.character.update_emotional_state import UpdateEmotionalStateSkill

        config_dir = _make_config_dir(tmp_path)
        state_dir = tmp_path / "state"
        llm_mock = _make_llm_mock([])

        skill = UpdateEmotionalStateSkill(llm_mock, config_dir=config_dir)
        result = await skill.run({
            "character_name": "zephyr",
            "contents": [{"index": 0, "summary": "テスト"}],
            "state_dir": str(state_dir),
        })

        assert result["character_name"] == "zephyr"

    @pytest.mark.asyncio
    async def test_run_deltas_applied_count(self, tmp_path):
        """deltas_applied は emotional_delta を持つコンテンツ件数を返す"""
        from skills.character.update_emotional_state import UpdateEmotionalStateSkill

        config_dir = _make_config_dir(tmp_path)
        state_dir = tmp_path / "state"
        llm_mock = _make_llm_mock([
            {"index": 0, "emotional_delta": {"curiosity": 0.1}},
            {"index": 1, "emotional_delta": {}},  # 空のデルタ
            {"index": 2, "emotional_delta": {"excitement": 0.2}},
        ])

        skill = UpdateEmotionalStateSkill(llm_mock, config_dir=config_dir)
        result = await skill.run({
            "character_name": "zephyr",
            "contents": [
                {"index": 0, "summary": "コンテンツA"},
                {"index": 1, "summary": "コンテンツB"},
                {"index": 2, "summary": "コンテンツC"},
            ],
            "state_dir": str(state_dir),
        })

        # emotional_delta が {} のものはカウントされない
        assert result["deltas_applied"] == 2

    @pytest.mark.asyncio
    async def test_run_loads_existing_state_file(self, tmp_path):
        """既存の感情状態 JSON から読み込んでデルタを加算する"""
        from skills.character.update_emotional_state import UpdateEmotionalStateSkill

        config_dir = _make_config_dir(tmp_path)
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        # 既存ファイルを用意（curiosity: 0.8）
        existing = {"curiosity": 0.80, "excitement": 0.50, "boredom": 0.30, "anxiety": 0.20}
        (state_dir / "emotional_state_zephyr.json").write_text(json.dumps(existing))

        llm_mock = _make_llm_mock([
            {"index": 0, "emotional_delta": {"curiosity": 0.1}},
        ])

        skill = UpdateEmotionalStateSkill(llm_mock, config_dir=config_dir)
        result = await skill.run({
            "character_name": "zephyr",
            "contents": [{"index": 0, "summary": "テスト"}],
            "state_dir": str(state_dir),
        })

        # 既存値 0.80 + delta 0.10 = 0.90
        assert result["updated_state"]["curiosity"] == pytest.approx(0.90)
