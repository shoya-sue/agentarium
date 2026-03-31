"""
core/skill_spec.py — Skill 定義 YAML → dataclass 変換

config/skills/{category}/{name}.yaml を読み込んで SkillSpec に変換する。
Phase 0 V5 検証済み: 20/20 YAML が正常ロード可能。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SkillSpec:
    """YAML から読み込んだ Skill 定義（イミュータブル）"""

    name: str
    version: str
    category: str
    phase: int
    description: str

    # 入力スキーマ（YAML の input セクションをそのまま保持）
    input_schema: dict[str, Any] = field(default_factory=dict)
    # 出力スキーマ（YAML の output セクション）
    output_schema: dict[str, Any] = field(default_factory=dict)

    # Qdrant 設定（memory Skill のみ）
    qdrant_config: dict[str, Any] | None = None
    # アダプタ設定（perception Skill のみ）
    adapter_config: dict[str, Any] | None = None
    # LLM 設定
    llm_config: dict[str, Any] | None = None

    # トレース設定
    trace_log_fields: list[str] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        """カテゴリ付き完全名（例: perception/browse_source）"""
        return f"{self.category}/{self.name}"


def load_skill_spec(yaml_path: Path) -> SkillSpec:
    """
    Skill YAML ファイルを読み込んで SkillSpec を返す。

    Args:
        yaml_path: config/skills/{category}/{name}.yaml へのパス

    Returns:
        SkillSpec インスタンス

    Raises:
        FileNotFoundError: ファイルが存在しない場合
        KeyError: 必須フィールドが欠落している場合
        yaml.YAMLError: YAML 構文エラーの場合
    """
    if not yaml_path.exists():
        raise FileNotFoundError(f"Skill YAML が見つかりません: {yaml_path}")

    with yaml_path.open(encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)

    # 必須フィールドの検証
    required_fields = ("name", "version", "category", "phase", "description")
    for field_name in required_fields:
        if field_name not in data:
            raise KeyError(f"必須フィールド '{field_name}' が欠落しています: {yaml_path}")

    trace_section = data.get("trace", {}) or {}

    return SkillSpec(
        name=data["name"],
        version=str(data["version"]),
        category=data["category"],
        phase=int(data["phase"]),
        description=data["description"],
        input_schema=data.get("input", {}),
        output_schema=data.get("output", {}),
        qdrant_config=data.get("qdrant"),
        adapter_config=data.get("adapter"),
        llm_config=data.get("llm"),
        trace_log_fields=trace_section.get("log_fields", []),
    )


def load_all_skill_specs(base_path: Path) -> dict[str, SkillSpec]:
    """
    base_path 以下の全 YAML を読み込んで名前→SkillSpec の辞書を返す。

    Args:
        base_path: config/skills/ ディレクトリへのパス

    Returns:
        {skill_name: SkillSpec} の辞書
    """
    specs: dict[str, SkillSpec] = {}
    for yaml_file in sorted(base_path.rglob("*.yaml")):
        spec = load_skill_spec(yaml_file)
        specs[spec.name] = spec
    return specs
