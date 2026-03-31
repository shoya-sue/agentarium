"""
core/skill_engine.py — Skill 実行エンジン

Phase 1: ルールベースで Skill を実行する。
Phase 2 以降: LLM 駆動の Skill 選択に移行予定（D4 決定事項）。

設計原則:
  - Skill 単一責任: 各 Skill は 1 つの機能に集中
  - Skill 間の状態共有禁止
  - 全実行に SkillTrace 付与
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Awaitable

from .skill_spec import SkillSpec, load_skill_spec
from .skill_trace import SkillTrace

logger = logging.getLogger(__name__)

# Skill ハンドラの型: 入力パラメータ → 出力（非同期）
SkillHandler = Callable[[dict[str, Any]], Awaitable[Any]]


class SkillEngine:
    """
    Skill を登録・実行するエンジン。

    使用例::

        engine = SkillEngine(
            config_base=Path("config"),
            traces_dir=Path("data/traces"),
        )
        engine.register("browse_source", browse_source_handler)
        result = await engine.run("browse_source", {"source_id": "hacker_news"})
    """

    def __init__(
        self,
        config_base: Path,
        traces_dir: Path,
    ) -> None:
        self._config_base = config_base
        self._traces_dir = traces_dir
        self._handlers: dict[str, SkillHandler] = {}
        self._specs: dict[str, SkillSpec] = {}

    def register(
        self,
        skill_name: str,
        handler: SkillHandler,
        spec_path: Path | None = None,
    ) -> None:
        """
        Skill ハンドラを登録する。

        Args:
            skill_name: Skill 名（例: "browse_source"）
            handler: 非同期ハンドラ関数
            spec_path: YAML パスを明示する場合（省略時は自動検索）
        """
        if spec_path is None:
            # config/skills/ 以下を再帰検索
            found = list(self._config_base.rglob(f"skills/**/{skill_name}.yaml"))
            if not found:
                logger.warning("SkillSpec YAML が見つかりません: %s", skill_name)
            else:
                self._specs[skill_name] = load_skill_spec(found[0])
        else:
            self._specs[skill_name] = load_skill_spec(spec_path)

        self._handlers[skill_name] = handler
        logger.info("Skill 登録: %s", skill_name)

    async def run(
        self,
        skill_name: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """
        Skill を実行してトレース付きで結果を返す。

        Args:
            skill_name: 実行する Skill 名
            params: 入力パラメータ

        Returns:
            Skill ハンドラの戻り値

        Raises:
            KeyError: 未登録の Skill を指定した場合
            RuntimeError: Skill 実行エラー（エラー詳細はトレースに記録）
        """
        if skill_name not in self._handlers:
            raise KeyError(f"未登録の Skill: {skill_name}")

        input_params = params or {}
        trace = SkillTrace.start(skill_name, input_params)

        try:
            handler = self._handlers[skill_name]
            result = await handler(input_params)

            # result_count を自動推定
            count = len(result) if isinstance(result, (list, dict)) else None
            trace.finish(result=result, result_count=count)

        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            trace.fail(error=error_msg)
            logger.error("Skill 実行エラー [%s]: %s", skill_name, error_msg)
            raise RuntimeError(f"Skill '{skill_name}' の実行に失敗しました: {error_msg}") from exc

        finally:
            # 常にトレースを保存
            trace.save(self._traces_dir)
            spec = self._specs.get(skill_name)
            log_fields = spec.trace_log_fields if spec else None
            trace.log(log_fields)

        return result

    @property
    def registered_skills(self) -> list[str]:
        """登録済み Skill 名の一覧"""
        return list(self._handlers.keys())
