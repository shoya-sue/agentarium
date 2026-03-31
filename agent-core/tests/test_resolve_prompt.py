"""
tests/test_resolve_prompt.py — ResolvePromptSkill ユニットテスト

YAML テンプレート読み込み・変数展開・output_schema 注入を検証する。
"""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def prompt_config_dir(tmp_path: Path) -> Path:
    """テスト用プロンプト設定ディレクトリを作成する fixture。"""
    system_dir = tmp_path / "prompts" / "system"
    user_dir = tmp_path / "prompts" / "user"
    schema_dir = tmp_path / "prompts" / "output_schema"
    system_dir.mkdir(parents=True)
    user_dir.mkdir(parents=True)
    schema_dir.mkdir(parents=True)

    # テスト用テンプレート
    (system_dir / "test_template.yaml").write_text(
        yaml.dump({
            "role": "system",
            "content": "あなたは {role_name} です。{output_schema}",
        })
    )
    (user_dir / "test_template.yaml").write_text(
        yaml.dump({
            "role": "user",
            "content": "次のトピックについて教えてください: {topic}",
        })
    )
    (schema_dir / "test_template.yaml").write_text(
        yaml.dump({
            "schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "score": {"type": "number"},
                },
            },
            "example": {"summary": "テスト概要", "score": 0.9},
        })
    )

    return tmp_path


class TestResolvePromptSkill:
    """ResolvePromptSkill の動作検証"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.reasoning.resolve_prompt import ResolvePromptSkill
        assert ResolvePromptSkill is not None

    @pytest.mark.asyncio
    async def test_basic_variable_substitution(self, prompt_config_dir: Path):
        """基本的な変数置換が正しく動作する"""
        from skills.reasoning.resolve_prompt import ResolvePromptSkill
        skill = ResolvePromptSkill(config_dir=prompt_config_dir)
        result = await skill.run({
            "template_name": "test_template",
            "variables": {"role_name": "AIアシスタント", "topic": "機械学習"},
            "include_output_schema": False,
        })

        assert result["template_name"] == "test_template"
        messages = result["messages"]
        assert len(messages) == 2

        system_msg = next(m for m in messages if m["role"] == "system")
        user_msg = next(m for m in messages if m["role"] == "user")

        assert "AIアシスタント" in system_msg["content"]
        assert "機械学習" in user_msg["content"]

    @pytest.mark.asyncio
    async def test_output_schema_injection(self, prompt_config_dir: Path):
        """output_schema が system メッセージに注入される"""
        from skills.reasoning.resolve_prompt import ResolvePromptSkill
        skill = ResolvePromptSkill(config_dir=prompt_config_dir)
        result = await skill.run({
            "template_name": "test_template",
            "variables": {"role_name": "レビュアー", "topic": "テスト"},
            "include_output_schema": True,
        })

        system_msg = next(m for m in result["messages"] if m["role"] == "system")
        # output_schema プレースホルダが実際のスキーマで置換されているはず
        assert "{output_schema}" not in system_msg["content"]
        # スキーマ情報が含まれているはず
        assert "summary" in system_msg["content"] or "score" in system_msg["content"]

    @pytest.mark.asyncio
    async def test_result_contains_resolved_at(self, prompt_config_dir: Path):
        """結果に resolved_at フィールドが含まれる"""
        from skills.reasoning.resolve_prompt import ResolvePromptSkill
        skill = ResolvePromptSkill(config_dir=prompt_config_dir)
        result = await skill.run({
            "template_name": "test_template",
            "variables": {"role_name": "bot", "topic": "test"},
            "include_output_schema": False,
        })
        assert "resolved_at" in result

    @pytest.mark.asyncio
    async def test_missing_template_raises_file_not_found(self, prompt_config_dir: Path):
        """存在しないテンプレートで FileNotFoundError が発生"""
        from skills.reasoning.resolve_prompt import ResolvePromptSkill
        skill = ResolvePromptSkill(config_dir=prompt_config_dir)
        with pytest.raises(FileNotFoundError):
            await skill.run({
                "template_name": "nonexistent_template",
                "variables": {},
            })

    @pytest.mark.asyncio
    async def test_unreplaced_placeholder_remains_if_no_variable(self, prompt_config_dir: Path):
        """変数が指定されていないプレースホルダはそのまま残るか、空文字に置換される"""
        from skills.reasoning.resolve_prompt import ResolvePromptSkill
        skill = ResolvePromptSkill(config_dir=prompt_config_dir)
        # topic を渡さずに実行
        result = await skill.run({
            "template_name": "test_template",
            "variables": {"role_name": "bot"},
            "include_output_schema": False,
        })
        # エラーは発生しない（未置換のまま or 空文字）
        assert "messages" in result
