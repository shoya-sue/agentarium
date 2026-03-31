"""
tests/test_skill_spec.py — SkillSpec YAML ロードのユニットテスト

Phase 0 V5 検証: config/skills/ 以下の全 YAML が正常ロードできることを確認。
"""

import pytest
from pathlib import Path

# テスト実行時は agentarium/ をルートとして扱う
AGENTARIUM_ROOT = Path(__file__).parent.parent.parent  # agent-core/ の 1 つ上 = agentarium/
CONFIG_SKILLS_DIR = AGENTARIUM_ROOT / "config" / "skills"

# テスト対象モジュール（src/ 配下）
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.skill_spec import load_skill_spec, load_all_skill_specs, SkillSpec


class TestLoadSkillSpec:
    """load_skill_spec 単体テスト"""

    def test_load_browse_source(self):
        """browse_source.yaml を正常にロードできる"""
        yaml_path = CONFIG_SKILLS_DIR / "perception" / "browse_source.yaml"
        spec = load_skill_spec(yaml_path)

        assert isinstance(spec, SkillSpec)
        assert spec.name == "browse_source"
        assert spec.category == "perception"
        assert spec.phase == 1
        assert spec.version == "1.0.0"
        assert "ソースアダプタ" in spec.description
        assert spec.adapter_config is not None

    def test_load_store_episodic(self):
        """store_episodic.yaml を正常にロードできる"""
        yaml_path = CONFIG_SKILLS_DIR / "memory" / "store_episodic.yaml"
        spec = load_skill_spec(yaml_path)

        assert spec.name == "store_episodic"
        assert spec.category == "memory"
        assert spec.qdrant_config is not None
        assert spec.qdrant_config["collection"] == "episodic"

    def test_load_store_semantic(self):
        """store_semantic.yaml を正常にロードできる"""
        yaml_path = CONFIG_SKILLS_DIR / "memory" / "store_semantic.yaml"
        spec = load_skill_spec(yaml_path)

        assert spec.name == "store_semantic"
        assert spec.category == "memory"
        assert spec.qdrant_config is not None
        assert spec.qdrant_config["collection"] == "semantic"
        assert spec.qdrant_config["vector_size"] == 768

    def test_full_name_property(self):
        """full_name プロパティが category/name 形式を返す"""
        yaml_path = CONFIG_SKILLS_DIR / "perception" / "browse_source.yaml"
        spec = load_skill_spec(yaml_path)
        assert spec.full_name == "perception/browse_source"

    def test_file_not_found(self):
        """存在しないファイルで FileNotFoundError が発生する"""
        with pytest.raises(FileNotFoundError):
            load_skill_spec(Path("/nonexistent/path.yaml"))

    def test_spec_is_frozen(self):
        """SkillSpec はイミュータブル（frozen=True）"""
        yaml_path = CONFIG_SKILLS_DIR / "perception" / "browse_source.yaml"
        spec = load_skill_spec(yaml_path)
        with pytest.raises((AttributeError, TypeError)):
            spec.name = "modified"  # type: ignore


class TestLoadAllSkillSpecs:
    """load_all_skill_specs 統合テスト"""

    def test_load_all_from_config(self):
        """config/skills/ 以下の全 YAML をロードできる（Phase 0 V5 相当）"""
        if not CONFIG_SKILLS_DIR.exists():
            pytest.skip("config/skills/ が存在しません")

        specs = load_all_skill_specs(CONFIG_SKILLS_DIR)

        # 最低限 browse_source / store_episodic / store_semantic が含まれること
        assert "browse_source" in specs
        assert "store_episodic" in specs
        assert "store_semantic" in specs

        # 全て SkillSpec インスタンスであること
        for name, spec in specs.items():
            assert isinstance(spec, SkillSpec), f"{name} が SkillSpec でない"
            assert spec.name == name, f"YAML の name フィールドがファイル名と一致しない: {name}"
