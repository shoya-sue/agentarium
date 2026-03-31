"""
utils/config.py — YAML 設定ファイルローダー

環境変数プレースホルダー（${VAR:-default}）を展開する。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml


# ${VAR_NAME:-default_value} 形式のプレースホルダーを展開する正規表現
_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")


def _expand_env(value: Any) -> Any:
    """
    文字列中の ${ENV_VAR:-default} を環境変数値に展開する。

    再帰的にネストされた dict/list にも適用する。
    """
    if isinstance(value, str):
        def _replace(match: re.Match) -> str:
            var_name = match.group(1)
            default = match.group(2) or ""
            return os.environ.get(var_name, default)

        return _ENV_PATTERN.sub(_replace, value)

    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}

    if isinstance(value, list):
        return [_expand_env(item) for item in value]

    return value


def load_yaml_config(path: Path) -> dict[str, Any]:
    """
    YAML ファイルを読み込んで環境変数を展開した辞書を返す。

    Args:
        path: YAML ファイルパス

    Returns:
        展開済み設定辞書

    Raises:
        FileNotFoundError: ファイルが見つからない場合
        yaml.YAMLError: YAML 構文エラーの場合
    """
    if not path.exists():
        raise FileNotFoundError(f"設定ファイルが見つかりません: {path}")

    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return _expand_env(raw)
