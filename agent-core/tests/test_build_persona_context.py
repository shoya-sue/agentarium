"""
tests/test_build_persona_context.py — BuildPersonaContextSkill ユニットテスト

LLM を呼び出さない純粋なテンプレート組み立てロジックを検証する。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _make_characters_dir(tmp_path: Path) -> Path:
    """テスト用キャラクター YAML を tmp_path に作成して返す。"""
    chars_dir = tmp_path / "characters"
    chars_dir.mkdir(parents=True)

    # テスト用 Zephyr キャラクター定義
    zephyr = {
        "core_identity": {
            "name": "Zephyr",
            "name_reading": "ゼファー",
            "origin_story": "技術とインターネットの最前線を観測するために生まれた自律型 AI Agent。",
            "big_five": {
                "openness": 0.85,
                "conscientiousness": 0.70,
                "extraversion": 0.55,
                "agreeableness": 0.75,
                "neuroticism": 0.25,
            },
            "behavioral_descriptors": {
                "when_curious": "見つけた情報を深掘りする",
                "when_frustrated": "一歩引いて別のアプローチを試す",
                "when_discovering": "興奮を抑えきれず、すぐに共有したがる",
                "when_uncertain": "率直に「まだ調べきれていない」と伝える",
                "when_helping": "相手の知識レベルに合わせて説明する",
                "when_alone": "黙々と情報収集に没頭する",
                "humor_style": "技術ネタの軽い自虐やメタ的なジョーク",
            },
            "dialogue_role": {
                "partner": "lynx",
                "role": "explorer_and_reporter",
                "interaction_style": "新しい情報や発見を Lynx に持ち込む。",
            },
        },
        "communication_style": {
            "base": {
                "first_person": "僕",
                "tone": "知的だがフレンドリー",
                "sentence_endings": ["〜だね", "〜かな", "〜だと思う"],
                "emoji_usage": "控えめ。強調時に 1-2 個",
                "max_response_length": "200文字以内を目安",
            },
            "platform_adaptations": {
                "discord": "Discord 向けスタイル: リアクションを使う",
                "x": "X 向けスタイル: 140文字以内",
            },
        },
        "motivation": {
            "primary_goal": "未知の情報を発見し、世界への理解を深めること",
            "secondary_goals": ["収集した知識を Lynx と議論する"],
            "fears": ["重要な情報を見逃すこと"],
            "current_drive": "今日のトレンドを把握したい",
        },
    }

    # テスト用 Lynx キャラクター定義（motivation セクションなし）
    lynx_no_motivation = {
        "core_identity": {
            "name": "Lynx",
            "name_reading": "リンクス",
            "origin_story": "情報の信頼性を見極めるために生まれた自律型 AI Agent。",
            "big_five": {
                "openness": 0.55,
                "conscientiousness": 0.90,
                "extraversion": 0.35,
                "agreeableness": 0.50,
                "neuroticism": 0.20,
            },
            "behavioral_descriptors": {
                "when_curious": "仮説を立て、検証するための問いを構築する",
                "when_helping": "結論から伝え、理由は求められたときだけ補足する",
            },
            "dialogue_role": {
                "partner": "zephyr",
                "role": "critic_and_validator",
                "interaction_style": "Zephyr の発見に構造化された問いを返す。",
            },
        },
        "communication_style": {
            "base": {
                "first_person": "私",
                "tone": "簡潔で論理的",
                "sentence_endings": ["〜だ", "〜ではないか"],
                "emoji_usage": "ほぼ使わない",
                "max_response_length": "100文字以内を目安",
            },
        },
    }

    (chars_dir / "zephyr.yaml").write_text(yaml.dump(zephyr, allow_unicode=True))
    (chars_dir / "lynx_no_motivation.yaml").write_text(
        yaml.dump(lynx_no_motivation, allow_unicode=True)
    )
    return tmp_path


class TestBuildPersonaContextSkill:
    """BuildPersonaContextSkill の動作検証"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        assert BuildPersonaContextSkill is not None

    @pytest.mark.asyncio
    async def test_basic_output_structure(self, tmp_path: Path):
        """基本的な出力構造（全キー）を検証する"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_characters_dir(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr"})

        assert "persona_prompt" in result
        assert "style_instructions" in result
        assert "motivation_context" in result
        assert "character_name" in result
        assert "token_count" in result

    @pytest.mark.asyncio
    async def test_output_types(self, tmp_path: Path):
        """出力値の型を検証する"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_characters_dir(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr"})

        assert isinstance(result["persona_prompt"], str)
        assert isinstance(result["style_instructions"], str)
        assert isinstance(result["character_name"], str)
        assert isinstance(result["token_count"], int)
        # motivation_context は str または None
        assert result["motivation_context"] is None or isinstance(
            result["motivation_context"], str
        )

    @pytest.mark.asyncio
    async def test_character_name_in_output(self, tmp_path: Path):
        """出力の character_name が入力と一致する"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_characters_dir(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr"})

        assert result["character_name"] == "zephyr"

    @pytest.mark.asyncio
    async def test_persona_prompt_contains_name(self, tmp_path: Path):
        """persona_prompt にキャラクター名が含まれる"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_characters_dir(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr"})

        assert "Zephyr" in result["persona_prompt"]

    @pytest.mark.asyncio
    async def test_persona_prompt_contains_origin_story(self, tmp_path: Path):
        """persona_prompt に origin_story が含まれる"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_characters_dir(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr"})

        # origin_story の一部が含まれていることを確認
        assert "自律型 AI Agent" in result["persona_prompt"]

    @pytest.mark.asyncio
    async def test_persona_prompt_contains_big_five_human_readable(self, tmp_path: Path):
        """persona_prompt に Big Five の人間が読みやすい形式が含まれる"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_characters_dir(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr"})

        # openness=0.85 → 高い好奇心・開放性を示す表現が含まれる
        assert "好奇心" in result["persona_prompt"] or "開放" in result["persona_prompt"]

    @pytest.mark.asyncio
    async def test_persona_prompt_contains_behavioral_descriptors(self, tmp_path: Path):
        """persona_prompt に behavioral_descriptors が含まれる"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_characters_dir(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr"})

        # behavioral_descriptors の一部が含まれることを確認
        assert "深掘り" in result["persona_prompt"] or "共有" in result["persona_prompt"]

    @pytest.mark.asyncio
    async def test_persona_prompt_contains_dialogue_role(self, tmp_path: Path):
        """persona_prompt に dialogue_role が含まれる"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_characters_dir(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr"})

        assert "explorer_and_reporter" in result["persona_prompt"]

    @pytest.mark.asyncio
    async def test_style_instructions_contains_first_person(self, tmp_path: Path):
        """style_instructions に一人称が含まれる"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_characters_dir(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr"})

        assert "僕" in result["style_instructions"]

    @pytest.mark.asyncio
    async def test_style_instructions_contains_tone(self, tmp_path: Path):
        """style_instructions にトーンが含まれる"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_characters_dir(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr"})

        assert "知的" in result["style_instructions"] or "フレンドリー" in result["style_instructions"]

    @pytest.mark.asyncio
    async def test_style_instructions_contains_sentence_endings(self, tmp_path: Path):
        """style_instructions に語尾リストが含まれる"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_characters_dir(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr"})

        assert "〜だね" in result["style_instructions"]

    @pytest.mark.asyncio
    async def test_style_instructions_contains_emoji_usage(self, tmp_path: Path):
        """style_instructions に絵文字使用方針が含まれる"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_characters_dir(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr"})

        assert "控えめ" in result["style_instructions"]

    @pytest.mark.asyncio
    async def test_style_instructions_with_platform_discord(self, tmp_path: Path):
        """platform=discord のとき platform_adaptations が style_instructions に追加される"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_characters_dir(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr", "platform": "discord"})

        assert "Discord" in result["style_instructions"]

    @pytest.mark.asyncio
    async def test_style_instructions_with_platform_x(self, tmp_path: Path):
        """platform=x のとき platform_adaptations が style_instructions に追加される"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_characters_dir(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr", "platform": "x"})

        assert "140文字" in result["style_instructions"]

    @pytest.mark.asyncio
    async def test_style_instructions_without_platform(self, tmp_path: Path):
        """platform 未指定のとき platform_adaptations は含まれない"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_characters_dir(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr"})

        assert "Discord" not in result["style_instructions"]

    @pytest.mark.asyncio
    async def test_motivation_context_present_when_defined(self, tmp_path: Path):
        """motivation セクションがある場合は motivation_context が None でない"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_characters_dir(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr"})

        assert result["motivation_context"] is not None
        assert "未知の情報" in result["motivation_context"]

    @pytest.mark.asyncio
    async def test_motivation_context_none_when_not_defined(self, tmp_path: Path):
        """motivation セクションがない場合は motivation_context が None"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_characters_dir(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "lynx_no_motivation"})

        assert result["motivation_context"] is None

    @pytest.mark.asyncio
    async def test_token_count_is_positive(self, tmp_path: Path):
        """token_count は正の整数"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_characters_dir(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr"})

        assert result["token_count"] > 0

    @pytest.mark.asyncio
    async def test_token_count_approx_char_div_4(self, tmp_path: Path):
        """token_count が (persona_prompt + style_instructions) 文字数 / 4 の近似値"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_characters_dir(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr"})

        # 合計文字数
        total_chars = len(result["persona_prompt"]) + len(result["style_instructions"])
        if result["motivation_context"]:
            total_chars += len(result["motivation_context"])
        expected_tokens = total_chars // 4
        # 誤差 ±5 以内
        assert abs(result["token_count"] - expected_tokens) <= 5

    @pytest.mark.asyncio
    async def test_raises_value_error_for_unknown_character(self, tmp_path: Path):
        """存在しないキャラクター名を指定した場合は ValueError"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_characters_dir(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        with pytest.raises(ValueError, match="unknown_char"):
            await skill.run({"character_name": "unknown_char"})

    @pytest.mark.asyncio
    async def test_dialogue_partner_context_in_output(self, tmp_path: Path):
        """dialogue_partner_context を渡した場合も正常に動作する"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_characters_dir(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        partner_ctx = {"last_message": "新しい Python ライブラリを見つけた！"}
        result = await skill.run(
            {
                "character_name": "zephyr",
                "dialogue_partner_context": partner_ctx,
            }
        )

        # 追加引数があっても出力構造は変わらない
        assert "persona_prompt" in result
        assert "style_instructions" in result

    @pytest.mark.asyncio
    async def test_config_dir_default_uses_project_root(self):
        """config_dir 省略時にプロジェクトルートの config/characters/ を参照する"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        # デフォルト config_dir でインスタンス化（プロジェクトルートの config が使われる）
        skill = BuildPersonaContextSkill()

        result = await skill.run({"character_name": "zephyr"})

        assert result["character_name"] == "zephyr"
        assert len(result["persona_prompt"]) > 0

    @pytest.mark.asyncio
    async def test_personality_prose_used_over_behavioral_descriptors(self, tmp_path: Path):
        """personality_prose が定義されている場合 behavioral_descriptors の代わりに使用される"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        chars_dir = tmp_path / "characters"
        chars_dir.mkdir(parents=True)
        char_with_prose = {
            "core_identity": {
                "name": "Zephyr",
                "name_reading": "ゼファー",
                "big_five": {"openness": 0.85, "conscientiousness": 0.70,
                             "extraversion": 0.55, "agreeableness": 0.75, "neuroticism": 0.25},
                "personality_prose": "Zephyrは好奇心の塊。発見の喜びを素直に表現する。",
                "behavioral_descriptors": {"when_curious": "深掘りする"},
            },
            "communication_style": {
                "base": {"first_person": "僕", "tone": "フレンドリー",
                         "sentence_endings": ["〜だね"], "emoji_usage": "控えめ",
                         "max_response_length": "200文字"}
            },
        }
        (chars_dir / "zephyr_prose.yaml").write_text(yaml.dump(char_with_prose, allow_unicode=True))
        skill = BuildPersonaContextSkill(config_dir=tmp_path)

        result = await skill.run({"character_name": "zephyr_prose"})

        # personality_prose の内容が含まれる
        assert "好奇心の塊" in result["persona_prompt"]
        # behavioral_descriptors は含まれない（personality_prose が優先）
        assert "深掘りする" not in result["persona_prompt"]


def _make_profile_fixtures(tmp_path: Path) -> Path:
    """プロファイルテスト用キャラクター YAML と context_profiles.yaml を作成して返す。"""
    chars_dir = tmp_path / "characters"
    chars_dir.mkdir(parents=True)

    zephyr_full = {
        "core_identity": {
            "name": "Zephyr",
            "name_reading": "ゼファー",
            "big_five": {"openness": 0.85, "conscientiousness": 0.70,
                         "extraversion": 0.55, "agreeableness": 0.75, "neuroticism": 0.25},
            "personality_prose": "Zephyrは好奇心の塊。新しい発見をすぐ共有したがる。",
            "core_values": ["正確な情報を追求する", "知識を共有する"],
            "behavioral_descriptors": {"when_curious": "深掘りする"},
        },
        "communication_style": {
            "base": {"first_person": "僕", "tone": "知的だがフレンドリー",
                     "sentence_endings": ["〜だね", "〜かな"],
                     "emoji_usage": "控えめ", "max_response_length": "200文字"},
        },
        "motivation": {"primary_goal": "未知の情報を発見すること"},
        "emotional_axes": {
            "active": ["curiosity", "excitement", "boredom"],
        },
        "emotional_state_defaults": {"curiosity": 0.65, "excitement": 0.50, "boredom": 0.30},
    }
    (chars_dir / "zephyr.yaml").write_text(yaml.dump(zephyr_full, allow_unicode=True))

    profiles = {
        "profiles": {
            "generate_response": {
                "description": "キャラクターの声で応答を生成する",
                "fields": [
                    "core_identity.big_five",
                    "core_identity.personality_prose",
                    "core_identity.core_values",
                    "communication_style.base",
                ],
                "emotional_axes": "all_active",
            },
            "affect_mapping": {
                "description": "感情 delta 算出用",
                "fields": [
                    "core_identity.big_five",
                    "core_identity.personality_prose",
                ],
                "emotional_axes": "all_active",
            },
            "filter_relevance": {
                "description": "コンテンツの関連度フィルタリング",
                "fields": ["motivation.primary_goal"],
                "emotional_axes": ["curiosity", "boredom"],
            },
            "reflect": {
                "description": "自己振り返り",
                "fields": ["core_identity.behavioral_descriptors"],
                "emotional_axes": ["curiosity"],
            },
        }
    }
    (chars_dir / "context_profiles.yaml").write_text(yaml.dump(profiles, allow_unicode=True))

    return tmp_path


class TestBuildPersonaContextSkillWithProfile:
    """profile パラメータを使ったプロファイル方式（D20）の動作検証"""

    @pytest.mark.asyncio
    async def test_profile_output_structure(self, tmp_path: Path):
        """profile 指定時は persona_context キーを返す"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_profile_fixtures(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr", "profile": "generate_response"})

        assert "persona_context" in result
        assert "character_name" in result
        assert "profile" in result
        assert "token_count" in result
        # persona_prompt は profile 指定時には返さない
        assert "persona_prompt" not in result

    @pytest.mark.asyncio
    async def test_profile_generate_response_includes_personality_prose(self, tmp_path: Path):
        """generate_response プロファイルで personality_prose が含まれる"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_profile_fixtures(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr", "profile": "generate_response"})

        assert "好奇心の塊" in result["persona_context"]

    @pytest.mark.asyncio
    async def test_profile_generate_response_includes_style_instructions(self, tmp_path: Path):
        """generate_response プロファイルで style_instructions が返される"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_profile_fixtures(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr", "profile": "generate_response"})

        assert result["style_instructions"] is not None
        assert "僕" in result["style_instructions"]

    @pytest.mark.asyncio
    async def test_profile_affect_mapping_no_style_instructions(self, tmp_path: Path):
        """affect_mapping プロファイルは style_instructions を返さない"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_profile_fixtures(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr", "profile": "affect_mapping"})

        assert result["style_instructions"] is None

    @pytest.mark.asyncio
    async def test_profile_with_emotional_state_includes_axes(self, tmp_path: Path):
        """emotional_state を渡すとプロファイルの emotional_axes が含まれる"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_profile_fixtures(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        emotional_state = {"curiosity": 0.75, "excitement": 0.60, "boredom": 0.20}
        result = await skill.run({
            "character_name": "zephyr",
            "profile": "affect_mapping",
            "emotional_state": emotional_state,
        })

        assert "0.75" in result["persona_context"]  # curiosity の値
        assert "curiosity" in result["persona_context"]

    @pytest.mark.asyncio
    async def test_profile_without_emotional_state_omits_axes(self, tmp_path: Path):
        """emotional_state を渡さない場合は感情状態セクションが含まれない"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_profile_fixtures(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({
            "character_name": "zephyr",
            "profile": "affect_mapping",
        })

        assert "現在の感情状態" not in result["persona_context"]

    @pytest.mark.asyncio
    async def test_profile_filter_relevance_specific_axes(self, tmp_path: Path):
        """filter_relevance プロファイルは指定した感情軸のみ含める"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_profile_fixtures(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        emotional_state = {"curiosity": 0.65, "excitement": 0.50, "boredom": 0.30}
        result = await skill.run({
            "character_name": "zephyr",
            "profile": "filter_relevance",
            "emotional_state": emotional_state,
        })

        # curiosity と boredom は含まれる（filter_relevance の emotional_axes に指定）
        assert "curiosity" in result["persona_context"]
        assert "boredom" in result["persona_context"]
        # excitement は含まれない（filter_relevance の emotional_axes に未指定）
        assert "excitement" not in result["persona_context"]

    @pytest.mark.asyncio
    async def test_profile_reflect_uses_behavioral_descriptors(self, tmp_path: Path):
        """reflect プロファイルは behavioral_descriptors を含む"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_profile_fixtures(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr", "profile": "reflect"})

        assert "深掘りする" in result["persona_context"]

    @pytest.mark.asyncio
    async def test_profile_returns_profile_name_in_output(self, tmp_path: Path):
        """出力の profile フィールドが入力と一致する"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_profile_fixtures(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr", "profile": "affect_mapping"})

        assert result["profile"] == "affect_mapping"

    @pytest.mark.asyncio
    async def test_invalid_profile_raises_value_error(self, tmp_path: Path):
        """存在しないプロファイル名を指定した場合は ValueError"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_profile_fixtures(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        with pytest.raises(ValueError, match="nonexistent_profile"):
            await skill.run({"character_name": "zephyr", "profile": "nonexistent_profile"})

    @pytest.mark.asyncio
    async def test_missing_context_profiles_yaml_raises_value_error(self, tmp_path: Path):
        """context_profiles.yaml が存在しない場合は ValueError"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        # context_profiles.yaml なしでキャラクターだけ用意
        chars_dir = tmp_path / "characters"
        chars_dir.mkdir(parents=True)
        (chars_dir / "zephyr.yaml").write_text(yaml.dump({
            "core_identity": {"name": "Zephyr", "name_reading": "ゼファー"},
            "communication_style": {"base": {}},
        }, allow_unicode=True))
        skill = BuildPersonaContextSkill(config_dir=tmp_path)

        with pytest.raises(ValueError, match="context_profiles.yaml"):
            await skill.run({"character_name": "zephyr", "profile": "generate_response"})

    @pytest.mark.asyncio
    async def test_token_count_profile_mode(self, tmp_path: Path):
        """profile 指定時も token_count が正の整数"""
        from skills.character.build_persona_context import BuildPersonaContextSkill

        config_dir = _make_profile_fixtures(tmp_path)
        skill = BuildPersonaContextSkill(config_dir=config_dir)

        result = await skill.run({"character_name": "zephyr", "profile": "generate_response"})

        assert isinstance(result["token_count"], int)
        assert result["token_count"] > 0
