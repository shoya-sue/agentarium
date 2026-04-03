"""
skills/character/map_message_emotion.py — クオリア構造学メッセージ感情マッピング Skill

キャラクター間メッセージを受信した際に、クオリア構造学（主観的体験の哲学的フレームワーク）
に基づいて感情軸スコアを更新する。

update_emotional_state（ニュースコンテンツベース）とは異なり、このSkillは
「受信者がメッセージをどのように主観的に体験するか」に焦点を当てる。
送信者のパーソナリティ、両者の関係性、メッセージの内容を総合的に考慮した
感情マッピングを行う。

Skill 入出力スキーマ: config/skills/character/map_message_emotion.yaml
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml

from core.working_memory import load_emotional_state, save_emotional_state
from utils.config import find_project_root

logger = logging.getLogger(__name__)

# プロジェクトルートから config/ / data/state/ への相対パス（Docker / ローカル両対応）
_PROJECT_ROOT = find_project_root(Path(__file__).resolve().parent)
_DEFAULT_CONFIG_DIR = _PROJECT_ROOT / "config"
_DEFAULT_STATE_DIR = _PROJECT_ROOT / "data" / "state"

# delta の適用範囲
_SCORE_MIN = 0.0
_SCORE_MAX = 1.0

# クオリア感情マッピング用デフォルトモデル（routing.yaml に設定がない場合のフォールバック）
_DEFAULT_QUALIA_MODEL = "qwen3.5:35b-a3b"


def _clamp(value: float) -> float:
    """スコアを 0.0〜1.0 の範囲に収める。"""
    return max(_SCORE_MIN, min(_SCORE_MAX, value))


def _build_qualia_prompt(
    character_name: str,
    partner_name: str,
    messages: list[dict[str, Any]],
    active_axes: list[str],
    personality_prose: str,
    big_five: dict[str, float],
    relationship_description: str,
    current_state: dict[str, float],
) -> str:
    """
    クオリア構造学に基づく感情マッピング用プロンプトを構築する。

    update_emotional_state の affect_mapping プロンプトとは異なり、
    「受信者の一人称・主観的体験（クオリア）」として感情変化を捉えるフレームを採用する。

    Args:
        character_name: 受信キャラクター名
        partner_name: 送信キャラクター名
        messages: 受信メッセージリスト [{"from_character", "content", "timestamp", "metadata"}]
        active_axes: 評価対象の感情軸リスト
        personality_prose: 自然言語性格描写
        big_five: Big Five スコア辞書
        relationship_description: パートナーとの関係性説明
        current_state: 現在の感情状態 {軸名: スコア}

    Returns:
        LLM への user メッセージ文字列
    """
    # Big Five を読みやすい形式に整形
    big_five_str = "\n".join(f"  - {k}: {v}" for k, v in big_five.items())

    # 評価対象の感情軸を整形
    axes_str = "\n".join(f"  - {ax}" for ax in active_axes)

    # 現在の感情状態を整形
    state_str = "\n".join(f"  - {k}: {v:.2f}" for k, v in current_state.items())

    # 受信メッセージを整形（複数メッセージに対応）
    messages_parts: list[str] = []
    for i, msg in enumerate(messages, start=1):
        sender = msg.get("from_character", partner_name)
        content = msg.get("content", "")
        timestamp = msg.get("timestamp", "")
        # メタデータがある場合は補足情報として追加
        metadata = msg.get("metadata", {})
        meta_note = ""
        if metadata:
            meta_items = ", ".join(f"{k}: {v}" for k, v in metadata.items())
            meta_note = f"\n    [メタデータ: {meta_items}]"
        timestamp_note = f" ({timestamp})" if timestamp else ""
        messages_parts.append(
            f"  メッセージ {i} — 送信者: {sender}{timestamp_note}\n"
            f"    「{content}」{meta_note}"
        )
    messages_str = "\n".join(messages_parts)

    return f"""あなたは {character_name} です。
パートナーの {partner_name} からメッセージを受け取りました。
このメッセージをあなたの主観的体験（クオリア）として、一人称で感じてください。

## あなた自身のプロフィール

名前: {character_name}

性格:
{personality_prose}

Big Five パーソナリティ:
{big_five_str}

## {partner_name} との関係性

{relationship_description}

## 現在の感情状態

{state_str}

## 評価する感情軸

{axes_str}

## 受け取ったメッセージ

{messages_str}

---

## 指示

上記のメッセージを {character_name} としての一人称視点・主観的体験（クオリア）として受け取ったとき、
あなたの感情軸にどのような変化が生じるかを分析してください。

- クオリア記述: メッセージを受け取った瞬間の主観的・感覚的体験を自然言語で記述してください
- 感情デルタ: 変化する感情軸のみ記載してください。delta は -1.0〜1.0 の範囲で指定してください
- 変化がない軸は含めないでください

以下の JSON 形式のみを出力してください（説明文不要）:

```json
{{
  "qualia_description": "メッセージを受け取った瞬間の主観的体験の記述（日本語）",
  "emotional_deltas": [
    {{"axis": "curiosity", "delta": 0.15, "reason": "新技術の話題で好奇心が刺激された"}}
  ]
}}
```"""


def _apply_qualia_deltas(
    current_state: dict[str, float],
    emotional_deltas: list[dict[str, Any]],
    active_axes: list[str],
) -> tuple[dict[str, float], list[dict[str, Any]], list[str]]:
    """
    クオリア感情デルタを現在の状態に適用する。

    active_axes に含まれない軸は無視する。
    各軸のスコアは 0.0〜1.0 にクランプする。

    Args:
        current_state: 現在の感情状態 {軸名: スコア}
        emotional_deltas: LLM 出力の delta リスト [{"axis", "delta", "reason"}]
        active_axes: 更新対象の感情軸リスト

    Returns:
        (updated_state, deltas_applied_list, axes_updated):
            更新後の状態、適用済みデルタ詳細リスト、更新された軸名リスト
    """
    # イミュータブルパターン: 元の状態を変更せず新しい辞書を作成
    new_state = dict(current_state)
    deltas_applied: list[dict[str, Any]] = []
    updated_axes: set[str] = set()

    for delta_item in emotional_deltas:
        axis: str = delta_item.get("axis", "")
        delta: float = delta_item.get("delta", 0.0)
        reason: str = delta_item.get("reason", "")

        # active_axes に含まれない軸はスキップ
        if axis not in active_axes:
            logger.debug("unknown axis '%s' をスキップ（active_axes 外）", axis)
            continue

        # delta が 0.0 の場合は変化なしとしてスキップ
        if delta == 0.0:
            continue

        current_score = new_state.get(axis, 0.5)
        new_score = _clamp(current_score + delta)
        new_state[axis] = new_score
        updated_axes.add(axis)

        deltas_applied.append({
            "axis": axis,
            "delta": delta,
            "new_score": new_score,
            "reason": reason,
        })

    return new_state, deltas_applied, sorted(updated_axes)


class MapMessageEmotionSkill:
    """
    map_message_emotion Skill の実装。

    キャラクター間メッセージを受信した際に、クオリア構造学に基づいて
    感情軸スコアを更新する。

    update_emotional_state（ニュースコンテンツ → 三人称的感情マッピング）とは異なり、
    このSkillは受信者の一人称・主観的体験（クオリア）として感情変化を捉える。
    """

    def __init__(
        self,
        llm_client: Any,  # LLMClient（models/llm.py）
        config_dir: Path | str | None = None,
        state_dir: Path | str | None = None,
    ) -> None:
        self._llm = llm_client
        self._config_dir = Path(config_dir) if config_dir is not None else _DEFAULT_CONFIG_DIR
        self._state_dir = Path(state_dir) if state_dir is not None else _DEFAULT_STATE_DIR

    def _load_character(self, character_name: str) -> dict[str, Any]:
        """キャラクター YAML を読み込む。"""
        char_path = self._config_dir / "characters" / f"{character_name}.yaml"
        if not char_path.exists():
            raise ValueError(f"キャラクター YAML が見つかりません: {char_path}")
        with char_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _get_qualia_model(self) -> str:
        """routing.yaml から map_message_emotion 用モデルを取得する。"""
        routing_path = self._config_dir / "llm" / "routing.yaml"
        if routing_path.exists():
            with routing_path.open(encoding="utf-8") as f:
                routing: dict[str, Any] = yaml.safe_load(f) or {}
            # routing.yaml に skill_models.map_message_emotion があれば優先使用
            qualia_model = (
                routing.get("skill_models", {}).get("map_message_emotion")
                or routing.get("ollama_defaults", {}).get("model", "")
            )
            if qualia_model:
                return qualia_model
        return _DEFAULT_QUALIA_MODEL

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        受信メッセージをクオリア構造学に基づいて感情軸スコアにマッピングする。

        Args:
            params:
                character_name (str): 受信キャラクター名（必須）
                messages (list[dict]): 受信メッセージリスト（必須）
                    各メッセージ: {"from_character", "content", "timestamp", "metadata"}
                persona_context (dict | None): 現在のペルソナコンテキスト（省略可）
                model (str | None): 使用モデル（省略時は routing.yaml 参照）

        Returns:
            {
                "character_name": str,
                "messages_processed": int,
                "deltas_applied": list[{"axis", "delta", "new_score", "reason"}],
                "axes_updated": list[str],
                "updated_state": dict[str, float],
                "qualia_description": str,
            }
            エラー時は上記に "error": str を追加し、感情状態は更新しない。
        """
        character_name: str = params["character_name"]
        messages: list[dict[str, Any]] = params["messages"]
        model: str | None = params.get("model")

        # エラー時の共通レスポンスベース
        error_base: dict[str, Any] = {
            "character_name": character_name,
            "messages_processed": 0,
            "deltas_applied": [],
            "axes_updated": [],
            "updated_state": {},
        }

        if not messages:
            return {**error_base, "error": "messages が空です"}

        # キャラクター YAML 読み込み
        try:
            char_data = self._load_character(character_name)
        except ValueError as exc:
            logger.error("キャラクター YAML 読み込みエラー: %s", exc)
            raise  # missing_character_yaml は ValueError を re-raise

        # キャラクター情報の抽出
        core = char_data.get("core_identity", {})
        personality_prose: str = core.get("personality_prose", "")
        big_five: dict[str, float] = core.get("big_five", {})
        dialogue_role: dict[str, Any] = core.get("dialogue_role", {})
        partner_name: str = dialogue_role.get("partner", "unknown")
        relationship_description: str = dialogue_role.get("interaction_style", "")

        active_axes: list[str] = char_data.get("emotional_axes", {}).get("active", [])
        if not active_axes:
            raise ValueError(
                f"キャラクター '{character_name}' に emotional_axes.active が定義されていません"
            )

        # 感情状態の読み込み（未存在時は defaults から初期化）
        characters_dir = self._config_dir / "characters"
        current_state = load_emotional_state(character_name, self._state_dir, characters_dir)

        # クオリア構造学プロンプトを構築して LLM を呼び出す
        resolved_model = model or self._get_qualia_model()

        user_message = _build_qualia_prompt(
            character_name=character_name,
            partner_name=partner_name,
            messages=messages,
            active_axes=active_axes,
            personality_prose=personality_prose,
            big_five=big_five,
            relationship_description=relationship_description,
            current_state=current_state,
        )

        try:
            response = await self._llm.generate(
                prompt=user_message,
                model=resolved_model,
                think=False,
            )
        except Exception as exc:
            logger.error(
                "map_message_emotion: LLM 呼び出しエラー character=%s error=%s",
                character_name,
                exc,
            )
            return {**error_base, "error": str(exc)}

        # LLM 出力を JSON パース
        try:
            llm_result: dict[str, Any] = response.parse_json()
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error(
                "map_message_emotion: JSON パースエラー character=%s error=%s output=%s",
                character_name,
                exc,
                response.content[:500],
            )
            return {**error_base, "error": f"JSON パース失敗: {exc}"}

        # 必須フィールドの検証
        if not isinstance(llm_result, dict):
            err = f"LLM 出力が辞書形式ではありません: {type(llm_result)}"
            logger.error("map_message_emotion: %s", err)
            return {**error_base, "error": err}

        qualia_description: str = llm_result.get("qualia_description", "")
        emotional_deltas: list[dict[str, Any]] = llm_result.get("emotional_deltas", [])

        # デルタ適用（イミュータブル: 新しい状態辞書を返す）
        updated_state, deltas_applied, axes_updated = _apply_qualia_deltas(
            current_state, emotional_deltas, active_axes
        )

        # 永続化
        save_emotional_state(character_name, updated_state, self._state_dir)

        logger.info(
            "map_message_emotion: character=%s messages_processed=%d axes_updated=%s",
            character_name,
            len(messages),
            axes_updated,
        )

        return {
            "character_name": character_name,
            "messages_processed": len(messages),
            "deltas_applied": deltas_applied,
            "axes_updated": axes_updated,
            "updated_state": updated_state,
            "qualia_description": qualia_description,
        }
