"""
skills/character/build_persona_context.py — ペルソナコンテキスト組み立て Skill

キャラクター YAML を読み込み、LLM に渡すペルソナコンテキストを組み立てる。
LLM は呼び出さない（純粋なテンプレート組み立て）。

Phase 2 Batch 2b で実装。
Skill 入出力スキーマ: config/skills/character/build_persona_context.yaml
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# プロジェクトルートから config/characters/ への相対パス
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


def _build_persona_prompt(identity: dict[str, Any]) -> str:
    """core_identity からペルソナプロンプト文字列を組み立てる。"""
    parts: list[str] = []

    # キャラクター名と origin_story
    name = identity.get("name", "")
    origin_story = identity.get("origin_story", "")
    parts.append(f"あなたは {name}（{identity.get('name_reading', name)}）という AI Agent です。")
    if origin_story:
        parts.append(f"\n【バックグラウンド】\n{origin_story}")

    # Big Five パーソナリティ
    big_five = identity.get("big_five", {})
    if big_five:
        big_five_desc = _describe_big_five(big_five)
        parts.append(f"\n【パーソナリティ特性】\n{big_five_desc}")

    # 状況別の行動傾向
    behavioral = identity.get("behavioral_descriptors", {})
    if behavioral:
        behavior_lines = [f"  - {situation}: {desc}" for situation, desc in behavioral.items()]
        parts.append(f"\n【状況別の行動傾向】\n" + "\n".join(behavior_lines))

    # 対話役割
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
        parts.append(f"\n【対話における役割】\n" + "\n".join(role_parts))

    return "\n".join(parts)


def _build_style_instructions(
    comm_style: dict[str, Any],
    platform: str | None,
) -> str:
    """communication_style からスタイル指示文字列を組み立てる。"""
    base = comm_style.get("base", {})
    parts: list[str] = ["【スタイル指示】"]

    # 一人称
    first_person = base.get("first_person", "")
    if first_person:
        parts.append(f"  - 一人称: 「{first_person}」を使用する")

    # トーン
    tone = base.get("tone", "")
    if tone:
        parts.append(f"  - トーン: {tone}")

    # 語尾
    sentence_endings = base.get("sentence_endings", [])
    if sentence_endings:
        endings_str = "、".join(sentence_endings)
        parts.append(f"  - 語尾: {endings_str}")

    # 絵文字使用
    emoji_usage = base.get("emoji_usage", "")
    if emoji_usage:
        parts.append(f"  - 絵文字: {emoji_usage}")

    # 最大応答長
    max_length = base.get("max_response_length", "")
    if max_length:
        parts.append(f"  - 応答長: {max_length}")

    # プラットフォーム固有の適応
    if platform:
        adaptations = comm_style.get("platform_adaptations", {})
        platform_style = adaptations.get(platform, "")
        if platform_style:
            parts.append(f"\n【{platform} プラットフォーム向け追加指示】\n  {platform_style}")

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
    """

    def __init__(self, config_dir: Path | str | None = None) -> None:
        # config/characters/ ディレクトリを設定
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

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        キャラクター YAML からペルソナコンテキストを組み立てる。

        Args:
            params:
                character_name (str): キャラクター名 'zephyr' | 'lynx'（必須）
                platform (str | None): 出力先 'discord' | 'x' | None
                dialogue_partner_context (dict | None): 対話相手の直前発言サマリ

        Returns:
            persona_prompt (str): system prompt に挿入するペルソナ記述
            style_instructions (str): 文体・語尾・絵文字使用等のスタイル指示
            motivation_context (str | None): L2 Motivation のコンテキスト（未定義なら None）
            character_name (str): キャラクター名
            token_count (int): 推定トークン数（文字数 / 4）
        """
        character_name: str = params["character_name"]
        platform: str | None = params.get("platform")
        # dialogue_partner_context は現在は受け取るだけ（将来の拡張用）
        _dialogue_partner_context: dict[str, Any] | None = params.get(
            "dialogue_partner_context"
        )

        # キャラクター YAML 読み込み
        char_data = self._load_character(character_name)

        identity = char_data.get("core_identity", {})
        comm_style = char_data.get("communication_style", {})
        motivation = char_data.get("motivation")

        # 各セクションを組み立て
        persona_prompt = _build_persona_prompt(identity)
        style_instructions = _build_style_instructions(comm_style, platform)
        motivation_context = _build_motivation_context(motivation)

        # トークン数を推定（文字数 / 4）
        total_chars = len(persona_prompt) + len(style_instructions)
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
            "style_instructions": style_instructions,
            "motivation_context": motivation_context,
            "character_name": character_name,
            "token_count": token_count,
        }
