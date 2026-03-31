"""
V5: SkillSpec YAML → dataclass ロード検証
  - config/sources/*.yaml を全て SkillSpec dataclass に変換
  - config/skills/**/*.yaml を全て SkillSpec dataclass に変換
合格基準:
  - 全 YAML が正常にロードでき、必須フィールドが存在する
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

try:
    import yaml  # type: ignore
except ImportError:
    print("ERROR: PyYAML がインストールされていません。`pip install pyyaml`")
    sys.exit(1)

# プロジェクトルートを基準にする
PROJECT_ROOT = Path(__file__).parent.parent


@dataclass
class SkillSpec:
    """最小限の Skill 定義（Phase 0 検証用）"""
    name: str
    version: str
    description: str
    # オプションフィールド
    category: str = ""
    phase: int = 0
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    safety_ref: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class SourceSpec:
    """情報源アダプタ定義（config/sources/*.yaml）"""
    name: str
    type: str
    always_active: bool  # enabled の代わりに always_active or stealth_required を持つ
    description: str = ""
    phase: int = 0
    raw: dict = field(default_factory=dict)


def load_skill_spec(path: Path) -> Tuple[Optional[SkillSpec], str]:
    """YAML を読み込んで SkillSpec に変換。エラー時は (None, エラーメッセージ)"""
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return None, f"YAML パースエラー: {e}"
    except OSError as e:
        return None, f"ファイル読み込みエラー: {e}"

    if not isinstance(data, dict):
        return None, "YAML のトップレベルが dict ではありません"

    required = ["name", "version", "description"]
    missing = [k for k in required if k not in data]
    if missing:
        return None, f"必須フィールドが不足: {missing}"

    safety_ref = ""
    if "safety" in data and isinstance(data["safety"], dict):
        safety_ref = data["safety"].get("ref", "")

    spec = SkillSpec(
        name=data["name"],
        version=str(data["version"]),
        description=data["description"],
        category=data.get("category", ""),
        phase=data.get("phase", 0),
        input_schema=data.get("input", {}),
        output_schema=data.get("output", {}),
        safety_ref=safety_ref,
        raw=data,
    )
    return spec, ""


def load_source_spec(path: Path) -> Tuple[Optional[SourceSpec], str]:
    """config/sources/*.yaml を SourceSpec に変換"""
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return None, f"YAML パースエラー: {e}"
    except OSError as e:
        return None, f"ファイル読み込みエラー: {e}"

    if not isinstance(data, dict):
        return None, "YAML のトップレベルが dict ではありません"

    required = ["name", "type"]
    missing = [k for k in required if k not in data]
    if missing:
        return None, f"必須フィールドが不足: {missing}"

    spec = SourceSpec(
        name=data["name"],
        type=data["type"],
        always_active=bool(data.get("always_active", data.get("stealth_required") is not None)),
        description=data.get("description", ""),
        phase=data.get("phase", 0),
        raw=data,
    )
    return spec, ""


def test_sources() -> Tuple[int, int]:
    """config/sources/*.yaml を全て検証。(ok, total) を返す"""
    sources_dir = PROJECT_ROOT / "config" / "sources"
    yaml_files = sorted(sources_dir.glob("*.yaml"))

    if not yaml_files:
        print("  警告: config/sources/ に YAML ファイルが見つかりません")
        return 0, 0

    ok = 0
    for path in yaml_files:
        spec, err = load_source_spec(path)
        if spec is not None:
            print(f"  OK  {path.name:<35} name={spec.name!r} type={spec.type!r} always_active={spec.always_active}")
            ok += 1
        else:
            print(f"  FAIL {path.name:<34} {err}")
    return ok, len(yaml_files)


def test_skills() -> Tuple[int, int]:
    """config/skills/**/*.yaml を全て検証。(ok, total) を返す"""
    skills_dir = PROJECT_ROOT / "config" / "skills"
    yaml_files = sorted(skills_dir.rglob("*.yaml"))

    if not yaml_files:
        print("  警告: config/skills/ に YAML ファイルが見つかりません")
        return 0, 0

    ok = 0
    for path in yaml_files:
        spec, err = load_skill_spec(path)
        rel = path.relative_to(PROJECT_ROOT / "config" / "skills")
        if spec is not None:
            print(f"  OK  {str(rel):<45} name={spec.name!r} phase={spec.phase}")
            ok += 1
        else:
            print(f"  FAIL {str(rel):<44} {err}")
    return ok, len(yaml_files)


def test_characters() -> Tuple[int, int]:
    """config/characters/*.yaml の基本フィールド確認"""
    chars_dir = PROJECT_ROOT / "config" / "characters"
    yaml_files = sorted(chars_dir.glob("*.yaml"))

    if not yaml_files:
        print("  警告: config/characters/ に YAML ファイルが見つかりません")
        return 0, 0

    # キャラクターは core_identity 配下に name / big_five / dialogue_role が入る構造
    required_top = ["core_identity", "communication_style"]
    required_identity = ["name", "big_five", "dialogue_role"]
    ok = 0
    for path in yaml_files:
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            missing_top = [k for k in required_top if k not in data]
            if missing_top:
                print(f"  FAIL {path.name:<35} トップレベル不足: {missing_top}")
                continue
            identity = data["core_identity"]
            missing_id = [k for k in required_identity if k not in identity]
            if missing_id:
                print(f"  FAIL {path.name:<35} core_identity 不足: {missing_id}")
            else:
                name = identity.get("name", "?")
                partner = identity["dialogue_role"].get("partner", "?")
                print(f"  OK  {path.name:<35} name={name!r} partner={partner!r}")
                ok += 1
        except Exception as e:
            print(f"  FAIL {path.name:<35} {e}")
    return ok, len(yaml_files)


def main() -> None:
    print("=" * 60)
    print("V5: SkillSpec YAML ロード")
    print("=" * 60)
    print(f"プロジェクトルート: {PROJECT_ROOT}")

    print("\n--- config/sources/*.yaml ---")
    src_ok, src_total = test_sources()
    print(f"  {src_ok}/{src_total} OK")

    print("\n--- config/skills/**/*.yaml ---")
    skill_ok, skill_total = test_skills()
    print(f"  {skill_ok}/{skill_total} OK")

    print("\n--- config/characters/*.yaml ---")
    char_ok, char_total = test_characters()
    print(f"  {char_ok}/{char_total} OK")

    # 判定
    total_ok = src_ok + skill_ok + char_ok
    total_all = src_total + skill_total + char_total
    all_pass = (src_ok == src_total and skill_ok == skill_total and char_ok == char_total)

    print("\n--- 判定 ---")
    print(f"  合計: {total_ok}/{total_all} OK")
    if all_pass:
        print("合格: 全 YAML が正常にロードできます。")
    else:
        failed = total_all - total_ok
        print(f"注意: {failed} ファイルに問題があります。上記の FAIL を修正してください。")


if __name__ == "__main__":
    main()
