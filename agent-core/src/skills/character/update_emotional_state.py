"""
skills/character/update_emotional_state.py — 感情状態更新 Skill

filter_relevance を通過したコンテンツバッチを Qwen3.5-4B に渡し、
キャラクターの感情軸スコアを更新して data/state/ に永続化する（D18/D19）。

処理フロー:
  1. data/state/emotional_state_{character}.json を読み込む（未存在時は defaults から初期化）
  2. active_axes・personality_prose・big_five を YAML から取得
  3. コンテンツバッチを Qwen3.5-4B に渡して emotional_delta を取得
  4. 各軸に delta を加算（clamp: 0.0〜1.0）
  5. data/state/emotional_state_{character}.json に書き込む

Skill 入出力スキーマ: config/skills/character/update_emotional_state.yaml
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml

from core.working_memory import load_emotional_state, save_emotional_state

logger = logging.getLogger(__name__)

# プロジェクトルートから config/ への相対パス
_DEFAULT_CONFIG_DIR = Path(__file__).parent.parent.parent.parent.parent / "config"
_DEFAULT_STATE_DIR = Path(__file__).parent.parent.parent.parent.parent / "data" / "state"

# delta の適用範囲
_SCORE_MIN = 0.0
_SCORE_MAX = 1.0


def _clamp(value: float) -> float:
    """スコアを 0.0〜1.0 の範囲に収める。"""
    return max(_SCORE_MIN, min(_SCORE_MAX, value))


def _apply_deltas(
    current_state: dict[str, float],
    deltas: list[dict[str, Any]],
    active_axes: list[str],
) -> tuple[dict[str, float], list[str]]:
    """
    感情デルタを現在の状態に適用する。

    active_axes に含まれない軸は無視する。
    各軸のスコアは 0.0〜1.0 にクランプする。

    Args:
        current_state: 現在の感情状態 {軸名: スコア}
        deltas: LLM 出力の delta リスト [{index, emotional_delta: {軸名: delta}}]
        active_axes: 更新対象の感情軸リスト

    Returns:
        (updated_state, axes_updated): 更新後の状態と更新された軸名リスト
    """
    new_state = dict(current_state)
    updated_axes: set[str] = set()

    for delta_item in deltas:
        emotional_delta: dict[str, float] = delta_item.get("emotional_delta", {})
        for axis, delta in emotional_delta.items():
            if axis not in active_axes:
                continue
            current = new_state.get(axis, 0.5)
            new_state[axis] = _clamp(current + delta)
            updated_axes.add(axis)

    return new_state, sorted(updated_axes)


def _build_affect_mapping_prompt(
    character_name: str,
    personality_prose: str,
    big_five: dict[str, float],
    active_axes: list[str],
    current_state: dict[str, float],
    contents: list[dict[str, Any]],
) -> str:
    """
    affect_mapping 用のプロンプト文字列を構築する。

    Args:
        character_name: キャラクター名
        personality_prose: 自然言語性格描写
        big_five: Big Five スコア辞書
        active_axes: 評価対象の感情軸リスト
        current_state: 現在の感情状態
        contents: コンテンツリスト [{index, summary, topics}]

    Returns:
        LLM への user メッセージ文字列
    """
    big_five_str = "\n".join(f"  - {k}: {v}" for k, v in big_five.items())
    axes_str = "\n".join(f"  - {ax}" for ax in active_axes)
    state_str = "\n".join(f"  - {k}: {v:.2f}" for k, v in current_state.items())

    contents_items = []
    for c in contents:
        topics = ", ".join(c.get("topics", [])) if c.get("topics") else "未分類"
        contents_items.append(
            f'  - index {c["index"]}: {c["summary"]} [topics: {topics}]'
        )
    contents_str = "\n".join(contents_items)

    return f"""あなたは感情マッピングの専門システムです。
以下のキャラクター情報とコンテンツリストを分析し、
各コンテンツがキャラクターの感情軸に与える影響（delta）を JSON 配列で返してください。

## キャラクター情報

名前: {character_name}

性格:
{personality_prose}

Big Five:
{big_five_str}

## 評価する感情軸

{axes_str}

## 現在の感情状態

{state_str}

## コンテンツリスト

{contents_str}

---

## 出力形式

以下の JSON 配列のみを出力してください（説明文不要）。
感情変化がない軸は含めないでください。delta は -1.0〜1.0 の範囲で指定してください。

```json
[
  {{"index": 0, "emotional_delta": {{"curiosity": 0.2, "excitement": 0.1}}}},
  {{"index": 1, "emotional_delta": {{"boredom": 0.3}}}}
]
```"""


class UpdateEmotionalStateSkill:
    """
    update_emotional_state Skill の実装。

    コンテンツバッチを受け取り、キャラクターの感情軸スコアを更新する（D18/D19）。
    LLM（Qwen3.5-4B）を使用して感情デルタを算出する。
    """

    def __init__(
        self,
        llm_client: Any,  # LLMClient
        config_dir: Path | str | None = None,
    ) -> None:
        self._llm = llm_client
        if config_dir is None:
            config_dir = _DEFAULT_CONFIG_DIR
        self._config_dir = Path(config_dir)

    def _load_character(self, character_name: str) -> dict[str, Any]:
        """キャラクター YAML を読み込む。"""
        char_path = self._config_dir / "characters" / f"{character_name}.yaml"
        if not char_path.exists():
            raise ValueError(f"キャラクター YAML が見つかりません: {char_path}")
        with char_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _get_affect_model(self) -> str:
        """routing.yaml から affect_mapping 用モデルを取得する。"""
        routing_path = self._config_dir / "llm" / "routing.yaml"
        if routing_path.exists():
            with routing_path.open(encoding="utf-8") as f:
                routing: dict[str, Any] = yaml.safe_load(f) or {}
            # routing.yaml に skill_models.affect_mapping があれば使用
            affect_model = (
                routing.get("skill_models", {}).get("affect_mapping")
                or routing.get("ollama_defaults", {}).get("model", "")
            )
            if affect_model:
                return affect_model
        return "qwen3.5:4b"  # D19: デフォルトは 4B モデル

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        感情状態を更新する。

        Args:
            params:
                character_name (str): キャラクター名（必須）
                contents (list[dict]): コンテンツリスト [{index, summary, topics}]（必須）
                model (str | None): 使用モデル（省略時は routing.yaml 参照）
                state_dir (str | None): 感情状態 JSON のディレクトリ（省略時は data/state/）

        Returns:
            {
                "character_name": str,
                "updated_state": dict[str, float],
                "deltas_applied": int,
                "axes_updated": list[str],
            }
        """
        character_name: str = params["character_name"]
        contents: list[dict[str, Any]] = params["contents"]
        model: str | None = params.get("model")
        state_dir_override: str | None = params.get("state_dir")

        state_dir = (
            Path(state_dir_override)
            if state_dir_override
            else _DEFAULT_STATE_DIR
        )

        if not contents:
            raise ValueError("contents が空です")

        # キャラクター YAML 読み込み
        char_data = self._load_character(character_name)
        core = char_data.get("core_identity", {})
        personality_prose: str = core.get("personality_prose", "")
        big_five: dict[str, float] = core.get("big_five", {})
        active_axes: list[str] = (
            char_data.get("emotional_axes", {}).get("active", [])
        )

        if not active_axes:
            raise ValueError(
                f"キャラクター '{character_name}' に emotional_axes.active が定義されていません"
            )

        # 感情状態の読み込み（未存在時は defaults から初期化）
        characters_dir = self._config_dir / "characters"
        current_state = load_emotional_state(character_name, state_dir, characters_dir)

        # プロンプト構築 → LLM 呼び出し
        user_message = _build_affect_mapping_prompt(
            character_name=character_name,
            personality_prose=personality_prose,
            big_five=big_five,
            active_axes=active_axes,
            current_state=current_state,
            contents=contents,
        )

        resolved_model = model or self._get_affect_model()

        messages = [{"role": "user", "content": user_message}]
        response = await self._llm.generate(
            prompt=user_message,
            model=resolved_model,
            think=False,
        )

        # LLM 出力を JSON パース
        try:
            deltas: list[dict[str, Any]] = response.parse_json()
        except (json.JSONDecodeError, ValueError) as e:
            raise ValueError(f"LLM 出力の JSON パースに失敗: {e}\n出力: {response.content}") from e

        if not isinstance(deltas, list):
            raise ValueError(f"LLM 出力がリスト形式ではありません: {type(deltas)}")

        # デルタ適用
        updated_state, axes_updated = _apply_deltas(current_state, deltas, active_axes)
        deltas_applied = sum(
            1 for d in deltas if d.get("emotional_delta")
        )

        # 永続化
        save_emotional_state(character_name, updated_state, state_dir)

        logger.info(
            "update_emotional_state: character=%s axes_updated=%s deltas_applied=%d",
            character_name,
            axes_updated,
            deltas_applied,
        )

        return {
            "character_name": character_name,
            "updated_state": updated_state,
            "deltas_applied": deltas_applied,
            "axes_updated": axes_updated,
        }
