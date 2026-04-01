"""
tests/test_maintain_presence.py — MaintainPresenceSkill ユニットテスト

X / Discord プレゼンス維持の意思決定ロジックを検証する。
LLM 不要（ルールベース）。
"""

import asyncio
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _now_iso() -> str:
    """現在時刻の ISO 8601 文字列を返す。"""
    return datetime.now(timezone.utc).isoformat()


def _minutes_ago_iso(minutes: int) -> str:
    """n 分前の ISO 8601 文字列を返す。"""
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


class TestMaintainPresenceSkillImport:
    """インポートとクラス構造の確認"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.character.maintain_presence import MaintainPresenceSkill
        assert MaintainPresenceSkill is not None

    def test_instantiate(self):
        """インスタンス化できる"""
        from skills.character.maintain_presence import MaintainPresenceSkill
        skill = MaintainPresenceSkill()
        assert skill is not None

    def test_has_run_method(self):
        """run メソッドが存在する"""
        from skills.character.maintain_presence import MaintainPresenceSkill
        skill = MaintainPresenceSkill()
        assert callable(skill.run)


class TestMaintainPresenceSkillOutput:
    """出力スキーマの検証"""

    def test_basic_output_structure(self):
        """出力に action / platform / urgency が含まれる"""
        from skills.character.maintain_presence import MaintainPresenceSkill
        skill = MaintainPresenceSkill()
        result = asyncio.run(
            skill.run({
                "last_x_activity_at": _minutes_ago_iso(10),
                "last_discord_activity_at": _minutes_ago_iso(10),
            })
        )
        assert "action" in result
        assert "platform" in result
        assert "urgency" in result

    def test_urgency_is_float_in_range(self):
        """urgency が 0.0〜1.0 の float である"""
        from skills.character.maintain_presence import MaintainPresenceSkill
        skill = MaintainPresenceSkill()
        result = asyncio.run(
            skill.run({
                "last_x_activity_at": _minutes_ago_iso(5),
                "last_discord_activity_at": _minutes_ago_iso(5),
            })
        )
        assert isinstance(result["urgency"], float)
        assert 0.0 <= result["urgency"] <= 1.0

    def test_action_is_valid_string(self):
        """action が有効な文字列である"""
        from skills.character.maintain_presence import MaintainPresenceSkill, VALID_ACTIONS
        skill = MaintainPresenceSkill()
        result = asyncio.run(
            skill.run({
                "last_x_activity_at": _minutes_ago_iso(10),
                "last_discord_activity_at": _minutes_ago_iso(10),
            })
        )
        assert result["action"] in VALID_ACTIONS

    def test_platform_is_valid_string(self):
        """platform が x / discord / none のいずれか"""
        from skills.character.maintain_presence import MaintainPresenceSkill
        skill = MaintainPresenceSkill()
        result = asyncio.run(
            skill.run({
                "last_x_activity_at": _minutes_ago_iso(10),
                "last_discord_activity_at": _minutes_ago_iso(10),
            })
        )
        assert result["platform"] in ("x", "discord", "none")


class TestMaintainPresenceSkillDecisionLogic:
    """意思決定ロジックの検証"""

    def test_discord_overdue_recommends_discord_action(self):
        """Discord が 15 分以上無活動なら discord が推奨される"""
        from skills.character.maintain_presence import MaintainPresenceSkill
        skill = MaintainPresenceSkill()
        result = asyncio.run(
            skill.run({
                "last_x_activity_at": _minutes_ago_iso(5),     # X は最近活動済み
                "last_discord_activity_at": _minutes_ago_iso(20),  # Discord は 20 分前
            })
        )
        assert result["platform"] == "discord"

    def test_x_overdue_recommends_x_action(self):
        """X が 30 分以上無活動なら x が推奨される"""
        from skills.character.maintain_presence import MaintainPresenceSkill
        skill = MaintainPresenceSkill()
        result = asyncio.run(
            skill.run({
                "last_x_activity_at": _minutes_ago_iso(35),  # X は 35 分前
                "last_discord_activity_at": _minutes_ago_iso(5),  # Discord は最近
            })
        )
        assert result["platform"] == "x"

    def test_both_recent_returns_low_urgency(self):
        """両方が最近活動済みなら urgency が低い"""
        from skills.character.maintain_presence import MaintainPresenceSkill
        skill = MaintainPresenceSkill()
        result = asyncio.run(
            skill.run({
                "last_x_activity_at": _minutes_ago_iso(5),
                "last_discord_activity_at": _minutes_ago_iso(5),
            })
        )
        assert result["urgency"] < 0.5

    def test_discord_more_overdue_than_x_prefers_discord(self):
        """Discord が X よりも期限超過が大きい場合、Discord が優先される"""
        from skills.character.maintain_presence import MaintainPresenceSkill
        skill = MaintainPresenceSkill()
        # Discord 20分 > 閾値15分、X 10分 < 閾値30分
        result = asyncio.run(
            skill.run({
                "last_x_activity_at": _minutes_ago_iso(10),
                "last_discord_activity_at": _minutes_ago_iso(20),
            })
        )
        assert result["platform"] == "discord"

    def test_idle_action_when_both_recent(self):
        """両方が閾値内なら action が idle である"""
        from skills.character.maintain_presence import MaintainPresenceSkill
        skill = MaintainPresenceSkill()
        result = asyncio.run(
            skill.run({
                "last_x_activity_at": _minutes_ago_iso(2),
                "last_discord_activity_at": _minutes_ago_iso(2),
            })
        )
        assert result["action"] == "idle"

    def test_high_fatigue_reduces_urgency(self):
        """fatigue が高い場合、urgency が低くなる（疲労時は休む）"""
        from skills.character.maintain_presence import MaintainPresenceSkill
        skill = MaintainPresenceSkill()
        result_normal = asyncio.run(
            skill.run({
                "last_x_activity_at": _minutes_ago_iso(35),
                "last_discord_activity_at": _minutes_ago_iso(20),
                "fatigue": 0.1,
            })
        )
        result_tired = asyncio.run(
            skill.run({
                "last_x_activity_at": _minutes_ago_iso(35),
                "last_discord_activity_at": _minutes_ago_iso(20),
                "fatigue": 0.9,
            })
        )
        assert result_tired["urgency"] < result_normal["urgency"]

    def test_none_activity_time_treated_as_long_ago(self):
        """last_activity が None の場合、非常に古い時刻として扱われる"""
        from skills.character.maintain_presence import MaintainPresenceSkill
        skill = MaintainPresenceSkill()
        result = asyncio.run(
            skill.run({
                "last_x_activity_at": None,
                "last_discord_activity_at": _minutes_ago_iso(5),
            })
        )
        # X が null → 活動なしとして X を推奨
        assert result["platform"] == "x"
        assert result["urgency"] > 0.5
