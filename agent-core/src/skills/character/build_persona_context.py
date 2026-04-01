"""
skills/character/build_persona_context.py — ペルソナコンテキスト組み立て Skill

キャラクター YAML を読み込み、LLM に渡すペルソナコンテキストを組み立てる。
LLM は呼び出さない（純粋なテンプレート組み立て）。

Phase 2 Batch 2b で実装。D20: context_profiles.yaml 方式に対応。
Skill 入出力スキーマ: config/skills/character/build_persona_context.yaml
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# プロジェクトルートから config/ への相対パス
_DEFAULT_CONFIG_DIR = Path(__file__).parent.parent.parent.parent.parent / "config"

# Big Five スコアを人間が読みやすい表現にマッピング
_BIG_FIVE_LABELS: dict[str, list[tuple[float, str]]] = {
    "openness": [
        (0.8, "非常に好奇心旺盛で、新しいアイデアへの開放性が高い"),
        (0.6, "新しい概念に興味を持ちつつ、実証済みの知識も重視する"),
        (0.4, "新規情報には慎重で、実証済みの概念を優先する"),
        (0.0, "変化を好まず、確立された方法を強く重視する"),
    ],
    "conscientiousness": [
        (0.8, "非常に几帳面で、詳細と正確性に強いこだわりを持つ"),
        (0.6, "計画的で几帳面だが、柔軟性も持ち合わせる"),
        (0.4, "状況に応じて柔軟に対応し、厳密さより実用性を優先する"),
        (0.0, "自由奔放で、計画や手順にこだわらない"),
    ],
    "extraversion": [
        (0.7, "積極的に発信し、活発にコミュニケーションを取る"),
        (0.5, "適度に発信するが、押しつけがましくない"),
        (0.3, "発言は少ないが、核心を突く一言を大切にする"),
        (0.0, "内向的で、必要なときだけ発言する"),
    ],
    "agreeableness": [
        (0.7, "協調的で他者の意見を尊重するが、事実を曲げない"),
        (0.5, "協調的だが、誤りには容赦なく指摘する"),
        (0.3, "独立的で、他者の意見よりも自分の判断を優先する"),
        (0.0, "競争的で、対立を厭わない"),
    ],
    "neuroticism": [
        (0.0, "非常に安定していて、どんな状況でも冷静を保つ"),
        (0.3, "概ね安定しているが、特定の状況では敏感になることがある"),
        (0.5, "感情の起伏があり、ストレスに敏感な面がある"),
        (1.0, "感情の変動が大きく、不安を感じやすい"),
    ],
}


def _describe_big_five(big_five: dict[str, float]) -> str:
    """Big Five スコアを人間が読みやすい説明文に変換する。"""
    lines: list[str] = []

    for trait, value in big_five.items():
        thresholds = _BIG_FIVE_LABELS.get(trait, [])
        description = ""

        if trait == "neuroticism":
            # neuroticism は低いほど安定（昇順で最初にマッチするしきい値を使用）
            for threshold, label in thresholds:
                if value <= threshold:
                    description = label
                    break
            if not description and thresholds:
                description = thresholds[-1][1]
        else:
            # 他のトレイトは高いほど強い（降順で最初にマッチするしきい値を使用）
            for threshold, label in sorted(thresholds, key=lambda x: x[0], reverse=True):
                if value >= threshold:
                    description = label
                    break
            if not description and thresholds:
                description = thresholds[-1][1]

        if description:
            lines.append(f"  - {trait}: {description}")

    return "\n".join(lines)


def _get_nested(data: dict[str, Any], key_path: str) -> Any:
    """ドット区切りのキーパスでネストされた値を取得する。存在しない場合は None を返す。"""
    keys = key_path.split(".")
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None
    return current


def _build_style_instructions(
    comm_style: dict[str, Any],
    platform: str | None,
) -> str:
    """communication_style からスタイル指示文字列を組み立てる。"""
    base = comm_style.get("base", {})
    parts: list[str] = ["【スタイル指示】"]

    first_person = base.get("first_person", "")
    if first_person:
        parts.append(f"  - 一人称: 「{first_person}」を使用する")

    tone = base.get("tone", "")
    if tone:
        parts.append(f"  - トーン: {tone}")

    sentence_endings = base.get("sentence_endings", [])
    if sentence_endings:
        endings_str = "、".join(sentence_endings)
        parts.append(f"  - 語尾: {endings_str}")

    emoji_usage = base.get("emoji_usage", "")
    if emoji_usage:
        parts.append(f"  - 絵文字: {emoji_usage}")

    max_length = base.get("max_response_length", "")
    if max_length:
        parts.append(f"  - 応答長: {max_length}")

    if platform:
        adaptations = comm_style.get("platform_adaptations", {})
        platform_style = adaptations.get(platform, "")
        if platform_style:
            parts.append(f"\n【{platform} プラットフォーム向け追加指示】\n  {platform_style}")

    return "\n".join(parts)


def _build_emotional_state_section(
    char_data: dict[str, Any],
    emotional_axes_config: list[str] | str,
    emotional_state: dict[str, float],
) -> str | None:
    """感情状態セクションを組み立てる。対象軸がない場合は None を返す。"""
    if emotional_axes_config == "all_active":
        active_axes: list[str] = char_data.get("emotional_axes", {}).get("active", [])
        axes_to_include = [ax for ax in active_axes if ax in emotional_state]
    elif isinstance(emotional_axes_config, list):
        axes_to_include = [ax for ax in emotional_axes_config if ax in emotional_state]
    else:
        axes_to_include = []

    if not axes_to_include:
        return None

    axes_lines = [f"  - {ax}: {emotional_state[ax]:.2f}" for ax in axes_to_include]
    return "【現在の感情状態】\n" + "\n".join(axes_lines)


def _build_context_from_profile(
    char_data: dict[str, Any],
    profile_def: dict[str, Any],
    emotional_state: dict[str, float] | None,
    platform: str | None,
) -> tuple[str, str | None]:
    """
    プロファイル定義に基づいてペルソナコンテキストを組み立てる。

    Returns:
        (persona_context, style_instructions | None)
    """
    fields: list[str] = profile_def.get("fields", [])
    emotional_axes_config = profile_def.get("emotional_axes", [])

    identity = char_data.get("core_identity", {})
    name = identity.get("name", "")
    name_reading = identity.get("name_reading", name)

    parts: list[str] = [f"あなたは {name}（{name_reading}）という AI Agent です。"]

    for field_path in fields:
        value = _get_nested(char_data, field_path)
        if value is None:
            # Phase 2+ で有効化予定のフィールドは存在しなくても正常
            logger.debug("フィールド '%s' はキャラクター YAML に未定義（スキップ）", field_path)
            continue

        if field_path == "core_identity.big_five":
            big_five_desc = _describe_big_five(value)
            parts.append(f"\n【パーソナリティ特性（Big Five）】\n{big_five_desc}")

        elif field_path == "core_identity.personality_prose":
            parts.append(f"\n【性格】\n{value.strip()}")

        elif field_path == "core_identity.core_values":
            values_str = "\n".join(f"  - {v}" for v in value)
            parts.append(f"\n【価値観】\n{values_str}")

        elif field_path == "core_identity.behavioral_descriptors":
            # behavioral_descriptors は設計者向けのため、通常は LLM に渡さない
            # reflect プロファイルのみ例外的に使用（Phase 1-2）
            desc_lines = [f"  - {k}: {v}" for k, v in value.items()]
            parts.append("【状況別の行動傾向】\n" + "\n".join(desc_lines))

        elif field_path == "motivation.primary_goal":
            parts.append(f"\n【主目標】\n  {value}")

        elif field_path == "motivation.interests":
            if isinstance(value, list):
                interests_str = "\n".join(f"  - {i}" for i in value)
                parts.append(f"\n【興味・関心】\n{interests_str}")
            else:
                parts.append(f"\n【興味・関心】\n  {value}")

        # communication_style は style_instructions として別途構築するためスキップ
        elif field_path.startswith("communication_style."):
            pass

        # cognitive_state は Phase 3+ で有効化（現在は skip）
        elif field_path.startswith("cognitive_state."):
            pass

        else:
            logger.warning("未対応のフィールドパス: %s", field_path)

    # 感情状態セクション
    if emotional_state and emotional_axes_config:
        emotional_section = _build_emotional_state_section(
            char_data, emotional_axes_config, emotional_state
        )
        if emotional_section:
            parts.append(f"\n{emotional_section}")

    persona_context = "\n".join(parts)

    # style_instructions: communication_style フィールドが含まれる場合のみ構築
    style_instructions: str | None = None
    comm_style_fields = [f for f in fields if f.startswith("communication_style.")]
    if comm_style_fields:
        comm_style = char_data.get("communication_style", {})
        style_instructions = _build_style_instructions(comm_style, platform)

    return persona_context, style_instructions


def _build_persona_prompt(identity: dict[str, Any]) -> str:
    """core_identity からペルソナプロンプト文字列を組み立てる（profile=None 時の後方互換）。"""
    parts: list[str] = []

    name = identity.get("name", "")
    origin_story = identity.get("origin_story", "")
    parts.append(f"あなたは {name}（{identity.get('name_reading', name)}）という AI Agent です。")
    if origin_story:
        parts.append(f"\n【バックグラウンド】\n{origin_story}")

    big_five = identity.get("big_five", {})
    if big_five:
        big_five_desc = _describe_big_five(big_five)
        parts.append(f"\n【パーソナリティ特性】\n{big_five_desc}")

    # personality_prose を優先。なければ behavioral_descriptors にフォールバック（後方互換）
    personality_prose: str | None = identity.get("personality_prose")
    if personality_prose:
        parts.append(f"\n【性格】\n{personality_prose.strip()}")
    else:
        behavioral = identity.get("behavioral_descriptors", {})
        if behavioral:
            behavior_lines = [f"  - {situation}: {desc}" for situation, desc in behavioral.items()]
            parts.append("【状況別の行動傾向】\n" + "\n".join(behavior_lines))

    dialogue_role = identity.get("dialogue_role", {})
    if dialogue_role:
        role = dialogue_role.get("role", "")
        partner = dialogue_role.get("partner", "")
        interaction_style = dialogue_role.get("interaction_style", "")
        role_parts = [f"  - 役割: {role}"]
        if partner:
            role_parts.append(f"  - 対話相手: {partner}")
        if interaction_style:
            role_parts.append(f"  - 対話スタイル: {interaction_style.strip()}")
        parts.append("【対話における役割】\n" + "\n".join(role_parts))

    return "\n".join(parts)


def _build_motivation_context(motivation: dict[str, Any] | None) -> str | None:
    """motivation セクションからコンテキスト文字列を組み立てる。"""
    if not motivation:
        return None

    parts: list[str] = ["【現在のモチベーション】"]

    primary_goal = motivation.get("primary_goal", "")
    if primary_goal:
        parts.append(f"  - 主目標: {primary_goal}")

    secondary_goals = motivation.get("secondary_goals", [])
    if secondary_goals:
        goals_str = "\n".join(f"    - {g}" for g in secondary_goals)
        parts.append(f"  - サブ目標:\n{goals_str}")

    fears = motivation.get("fears", [])
    if fears:
        fears_str = "\n".join(f"    - {f}" for f in fears)
        parts.append(f"  - 恐れていること:\n{fears_str}")

    current_drive = motivation.get("current_drive", "")
    if current_drive:
        parts.append(f"  - 現在の駆動力: {current_drive}")

    return "\n".join(parts)


class BuildPersonaContextSkill:
    """
    build_persona_context Skill の実装。

    キャラクター YAML を読み込み、LLM に渡すペルソナコンテキストを組み立てる。
    LLM は呼び出さない。

    profile パラメータを指定すると context_profiles.yaml のプロファイル方式（D20）を使用する。
    profile=None の場合は後方互換の固定形式で出力する。
    """

    def __init__(self, config_dir: Path | str | None = None) -> None:
        if config_dir is None:
            self._chars_dir = _DEFAULT_CONFIG_DIR / "characters"
        else:
            self._chars_dir = Path(config_dir) / "characters"

    def _load_character(self, character_name: str) -> dict[str, Any]:
        """キャラクター YAML を読み込む。存在しない場合は ValueError を raise する。"""
        yaml_path = self._chars_dir / f"{character_name}.yaml"
        if not yaml_path.exists():
            raise ValueError(
                f"キャラクター '{character_name}' の YAML が見つかりません: {yaml_path}"
            )
        with yaml_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _load_profiles(self) -> dict[str, Any]:
        """context_profiles.yaml を読み込む。存在しない場合は ValueError を raise する。"""
        profiles_path = self._chars_dir / "context_profiles.yaml"
        if not profiles_path.exists():
            raise ValueError(f"context_profiles.yaml が見つかりません: {profiles_path}")
        with profiles_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("profiles", {})

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        キャラクター YAML からペルソナコンテキストを組み立てる。

        Args:
            params:
                character_name (str): キャラクター名 'zephyr' | 'lynx'（必須）
                profile (str | None): コンテキストプロファイル名（D20）
                    'filter_relevance' | 'generate_response' | 'reflect' |
                    'store_semantic' | 'affect_mapping' | None
                    None の場合は後方互換の固定形式で出力する。
                platform (str | None): 出力先 'discord' | 'x' | None
                emotional_state (dict[str, float] | None):
                    現在の感情状態（data/state/ から読み込み済みの値）。
                    profile が emotional_axes を持つ場合に使用する。
                dialogue_partner_context (dict | None): 対話相手の直前発言サマリ（将来拡張用）

        Returns:
            profile 指定時:
                persona_context (str): プロファイルに応じたペルソナコンテキスト
                style_instructions (str | None): スタイル指示（generate_response 時のみ）
                character_name (str): キャラクター名
                profile (str): 使用したプロファイル名
                token_count (int): 推定トークン数（文字数 / 4）
            profile=None 時（後方互換）:
                persona_prompt (str): system prompt に挿入するペルソナ記述
                style_instructions (str): スタイル指示
                motivation_context (str | None): L2 Motivation のコンテキスト
                character_name (str): キャラクター名
                token_count (int): 推定トークン数（文字数 / 4）
        """
        character_name: str = params["character_name"]
        profile: str | None = params.get("profile")
        platform: str | None = params.get("platform")
        emotional_state: dict[str, float] | None = params.get("emotional_state")

        char_data = self._load_character(character_name)

        if profile is not None:
            # D20: コンテキストプロファイル方式
            profiles = self._load_profiles()
            if profile not in profiles:
                raise ValueError(
                    f"プロファイル '{profile}' が context_profiles.yaml に未定義です。"
                    f" 有効値: {list(profiles.keys())}"
                )

            profile_def = profiles[profile]
            persona_context, style_instructions = _build_context_from_profile(
                char_data, profile_def, emotional_state, platform
            )

            total_chars = len(persona_context)
            if style_instructions:
                total_chars += len(style_instructions)
            token_count = total_chars // 4

            logger.info(
                "ペルソナコンテキスト組み立て完了（プロファイル方式）: "
                "character=%s profile=%s token_count=%d",
                character_name,
                profile,
                token_count,
            )

            return {
                "persona_context": persona_context,
                "style_instructions": style_instructions,
                "character_name": character_name,
                "profile": profile,
                "token_count": token_count,
            }

        else:
            # 後方互換: 固定形式で出力
            identity = char_data.get("core_identity", {})
            comm_style = char_data.get("communication_style", {})
            motivation = char_data.get("motivation")

            persona_prompt = _build_persona_prompt(identity)
            style_instructions_compat = _build_style_instructions(comm_style, platform)
            motivation_context = _build_motivation_context(motivation)

            total_chars = len(persona_prompt) + len(style_instructions_compat)
            if motivation_context:
                total_chars += len(motivation_context)
            token_count = total_chars // 4

            logger.info(
                "ペルソナコンテキスト組み立て完了: character=%s platform=%s token_count=%d",
                character_name,
                platform,
                token_count,
            )

            return {
                "persona_prompt": persona_prompt,
                "style_instructions": style_instructions_compat,
                "motivation_context": motivation_context,
                "character_name": character_name,
                "token_count": token_count,
            }
