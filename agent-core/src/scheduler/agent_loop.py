"""
scheduler/agent_loop.py — LLM 駆動自律ループ (Phase 2)

Phase 1 の PatrolScheduler（ルールベース）と並行して動作する。
1サイクルごとに「Skill選択 → 実行 → 記憶 → 振り返り」を繰り返す。

設計原則:
  - AgentLoop は軽量コーディネーター（ビジネスロジックは各 Skill に委譲）
  - WorkingMemory はイミュータブルパターンで更新
  - 各ステップで例外をキャッチしてループを継続
  - SafetyGuard によるサーキットブレーカー + レート制限
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from core.working_memory import WorkingMemory
from core.safety_guard import SafetyGuard
from utils.config import find_project_root

logger = logging.getLogger(__name__)

# デフォルトの IDLE スキル名
_IDLE_SKILL: str = "IDLE"

# 振り返りを行うサイクル間隔
_REFLECT_EVERY_N_CYCLES: int = 5

# 利用可能な Skill 名の固定リスト
_AVAILABLE_SKILL_NAMES: list[str] = [
    "fetch_hacker_news",
    "fetch_rss",
    "fetch_github_trending",
    "recall_related",
    "store_episodic",
    "store_semantic",
    "build_llm_context",
    "evaluate_importance",
    "select_skill",
    "plan_task",
    "reflect",
    "build_persona_context",
    "generate_response",
    "send_discord",
    _IDLE_SKILL,
]

# 利用可能な Skill のメタデータ（select_skill に渡す）
_AVAILABLE_SKILLS_META: list[dict[str, Any]] = [
    {
        "name": "fetch_hacker_news",
        "description": "Hacker News から最新記事を取得する",
        "when_to_use": "IT/技術ニュースの収集が必要なとき",
    },
    {
        "name": "fetch_rss",
        "description": "RSS フィードからコンテンツを取得する",
        "when_to_use": "特定のニュースソースを巡回するとき",
    },
    {
        "name": "fetch_github_trending",
        "description": "GitHub トレンドリポジトリを取得する",
        "when_to_use": "OSS の最新動向を収集するとき",
    },
    {
        "name": "recall_related",
        "description": "過去の記憶から関連情報を検索する",
        "when_to_use": "現在の話題に関連する過去の情報が必要なとき",
    },
    {
        "name": "store_episodic",
        "description": "エピソード記憶（出来事）を保存する",
        "when_to_use": "特定の出来事や実行結果を記録するとき",
    },
    {
        "name": "store_semantic",
        "description": "セマンティック記憶（知識）を保存する",
        "when_to_use": "コンテンツをベクトル化して長期記憶に保存するとき",
    },
    {
        "name": "build_llm_context",
        "description": "LLM に渡すコンテキストを構築する",
        "when_to_use": "LLM 呼び出し前にコンテキストを整理するとき",
    },
    {
        "name": "evaluate_importance",
        "description": "コンテンツの重要度を評価する",
        "when_to_use": "記憶するかどうかを判断するとき",
    },
    {
        "name": "select_skill",
        "description": "次に実行すべき Skill を選択する",
        "when_to_use": "意思決定が必要なとき（通常はループが自動的に呼び出す）",
    },
    {
        "name": "plan_task",
        "description": "目標を達成するための実行計画を立案する",
        "when_to_use": "複数ステップのタスクを計画するとき",
    },
    {
        "name": "reflect",
        "description": "実行サイクルを振り返り学習する",
        "when_to_use": "周期的な自己評価が必要なとき（通常はループが自動的に呼び出す）",
    },
    {
        "name": "build_persona_context",
        "description": "キャラクターのペルソナコンテキストを組み立てる",
        "when_to_use": "キャラクターとして応答する前に呼び出す",
    },
    {
        "name": "generate_response",
        "description": "キャラクターとして Discord/X 向けの応答を生成する",
        "when_to_use": "Discord や X に投稿するメッセージを生成するとき",
    },
    {
        "name": "send_discord",
        "description": "Discord Webhook にメッセージを送信する",
        "when_to_use": "Discord チャンネルにメッセージを投稿するとき",
    },
    {
        "name": _IDLE_SKILL,
        "description": "何もしない（待機）",
        "when_to_use": "特にすべきことがないとき",
    },
]


class AgentLoop:
    """
    LLM 駆動の自律ループ（Phase 2）。

    PatrolScheduler と並行して動作し、
    1サイクルごとに「Skill選択 → 実行 → 記憶 → 振り返り」を繰り返す。

    Args:
        character_name: キャラクター設定ファイル名（拡張子なし）
        cycle_interval_seconds: サイクル間隔（秒）
        max_cycles: 最大サイクル数（None = 無制限）
        config_dir: config/ ディレクトリのパス（None = デフォルト）
        skill_registry: 外部から Skill を注入するための辞書
                       {skill_name: async_callable}
                       テスト・依存性注入に使用する
    """

    def __init__(
        self,
        character_name: str = "agent_character",
        cycle_interval_seconds: float = 60.0,
        max_cycles: int | None = None,
        config_dir: Path | str | None = None,
        skill_registry: dict[str, Any] | None = None,
    ) -> None:
        self._character_name = character_name
        self._cycle_interval_seconds = cycle_interval_seconds
        self._max_cycles = max_cycles

        # config ディレクトリの解決（Docker / ローカル両対応）
        if config_dir is None:
            self._config_dir = find_project_root(Path(__file__).resolve().parent) / "config"
        else:
            self._config_dir = Path(config_dir)

        # WorkingMemory（イミュータブルパターン）
        self._memory: WorkingMemory = WorkingMemory()

        # SafetyGuard（サーキットブレーカー + レート制限）
        self._safety: SafetyGuard = SafetyGuard(config_dir=self._config_dir)

        # 外部注入 Skill レジストリ（テスト・DI 用）
        self._skill_registry: dict[str, Any] = skill_registry or {}

        # 実行状態
        self._running: bool = False
        self._cycle_count: int = 0

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """ループを開始する。"""
        if self._running:
            logger.warning("AgentLoop は既に起動中です")
            return
        self._running = True
        logger.info("AgentLoop 開始: character=%s interval=%.1fs", self._character_name, self._cycle_interval_seconds)
        await self._run_loop()

    async def stop(self) -> None:
        """ループを停止する。"""
        self._running = False
        logger.info("AgentLoop 停止 (cycle_count=%d)", self._cycle_count)

    @property
    def cycle_count(self) -> int:
        """現在のサイクル数を返す。"""
        return self._cycle_count

    @property
    def is_running(self) -> bool:
        """ループが実行中かどうかを返す。"""
        return self._running

    # ------------------------------------------------------------------
    # ループ制御
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """
        メインループ。

        max_cycles が設定されている場合はその回数で終了する。
        各サイクル後に cycle_interval_seconds 待機する。
        ループ終了後は _running を False にセットする。
        """
        while self._running and (
            self._max_cycles is None or self._cycle_count < self._max_cycles
        ):
            await self._run_cycle()
            # max_cycles に達した場合は待機しない
            if self._max_cycles is not None and self._cycle_count >= self._max_cycles:
                break
            if self._running:
                await asyncio.sleep(self._cycle_interval_seconds)

        # ループ終了後は _running を False にセット
        self._running = False

    # ------------------------------------------------------------------
    # 1サイクルの処理
    # ------------------------------------------------------------------

    async def _run_cycle(self) -> None:
        """
        1サイクルの処理:
        1. cycle_count インクリメント
        2. ペルソナ取得
        3. 記憶想起
        4. Skill 選択
        5. Safety チェック
        6. Skill 実行
        7. 重要度評価 → 必要ならエピソード記録
        8. 振り返り（5サイクルごと）
        """
        # 1. サイクルカウンタをインクリメント（イミュータブル更新）
        self._cycle_count += 1
        self._memory = self._memory.with_cycle_increment()

        logger.info("AgentLoop サイクル開始: cycle=%d", self._cycle_count)

        # 2. ペルソナコンテキスト取得
        persona_context: dict[str, Any] = {}
        try:
            persona_context = await self._call_skill(
                "build_persona_context",
                {"character_name": self._character_name},
            )
        except Exception as exc:
            logger.warning("サイクル %d: build_persona_context エラー: %s", self._cycle_count, exc)

        # 3. 記憶想起（現在の目標またはデフォルトクエリで検索）
        recall_query = self._memory.current_goal or "最近のエージェント活動"
        try:
            recalled = await self._call_skill(
                "recall_related",
                {"query": recall_query, "limit": 5},
            )
            if isinstance(recalled, list):
                self._memory = self._memory.with_recalled(recalled)
        except Exception as exc:
            logger.warning("サイクル %d: recall_related エラー: %s", self._cycle_count, exc)

        # 4. Skill 選択（LLM による意思決定）
        selected_skill: str = _IDLE_SKILL
        selected_params: dict[str, Any] = {}
        try:
            select_result = await self._call_skill(
                "select_skill",
                {
                    "available_skills": _AVAILABLE_SKILLS_META,
                    "current_state": self._memory.to_summary_dict(),
                    "persona_context": persona_context if persona_context else None,
                },
            )
            selected_skill = str(select_result.get("selected_skill", _IDLE_SKILL))
            selected_params = select_result.get("params", {})
            if not isinstance(selected_params, dict):
                selected_params = {}
        except Exception as exc:
            logger.warning("サイクル %d: select_skill エラー: %s", self._cycle_count, exc)
            selected_skill = _IDLE_SKILL

        # 5. IDLE の場合はサイクルをスキップ
        if selected_skill == _IDLE_SKILL:
            logger.info("サイクル %d: IDLE — Skill 実行をスキップ", self._cycle_count)
            await self._maybe_reflect()
            return

        # 6. Safety チェック（サーキットブレーカー + レート制限）
        safety_result = self._safety.check(selected_skill)
        if not safety_result.allowed:
            logger.warning(
                "サイクル %d: Safety 拒否 skill=%s reason=%s",
                self._cycle_count,
                selected_skill,
                safety_result.reason,
            )
            await self._maybe_reflect()
            return

        # 7. Skill 実行
        skill_result: dict[str, Any] = {}
        execution_error: str | None = None
        try:
            skill_result = await self._call_skill(selected_skill, selected_params)
            self._safety.record_success(selected_skill)

            # 実行結果をトレースに追加（イミュータブル更新）
            trace_entry: dict[str, Any] = {
                "skill_name": selected_skill,
                "status": "success",
                "cycle": self._cycle_count,
            }
            self._memory = self._memory.with_trace(trace_entry)

        except Exception as exc:
            execution_error = f"{type(exc).__name__}: {exc}"
            self._safety.record_failure(selected_skill)
            logger.error(
                "サイクル %d: Skill 実行エラー skill=%s error=%s",
                self._cycle_count,
                selected_skill,
                execution_error,
            )
            # 失敗トレースを記録してループ継続
            trace_entry = {
                "skill_name": selected_skill,
                "status": "failure",
                "error": execution_error,
                "cycle": self._cycle_count,
            }
            self._memory = self._memory.with_trace(trace_entry)
            await self._maybe_reflect()
            return

        # 8. 重要度評価 → 必要なら episodic 記憶に保存
        await self._evaluate_and_store(
            skill_name=selected_skill,
            skill_result=skill_result,
        )

        # 9. 振り返り（5サイクルごと）
        await self._maybe_reflect()

        logger.info("AgentLoop サイクル完了: cycle=%d skill=%s", self._cycle_count, selected_skill)

    # ------------------------------------------------------------------
    # 振り返り（5サイクルごと）
    # ------------------------------------------------------------------

    async def _maybe_reflect(self) -> None:
        """5サイクルごとに reflect Skill を呼び出す。"""
        if self._cycle_count % _REFLECT_EVERY_N_CYCLES != 0:
            return

        logger.info("サイクル %d: 振り返り実行", self._cycle_count)
        try:
            await self._call_skill(
                "reflect",
                {"working_memory": self._memory.to_summary_dict()},
            )
        except Exception as exc:
            logger.warning("サイクル %d: reflect エラー: %s", self._cycle_count, exc)

    # ------------------------------------------------------------------
    # 重要度評価 → episodic 保存
    # ------------------------------------------------------------------

    async def _evaluate_and_store(
        self,
        skill_name: str,
        skill_result: dict[str, Any],
    ) -> None:
        """
        実行結果の重要度を評価し、閾値を超えたら episodic 記憶に保存する。

        Args:
            skill_name: 実行した Skill 名
            skill_result: Skill の実行結果
        """
        # 結果を文字列に変換（重要度評価用）
        content = str(skill_result)[:500]  # 長すぎる場合は先頭500文字に制限

        try:
            importance_result = await self._call_skill(
                "evaluate_importance",
                {
                    "content": content,
                    "source": skill_name,
                },
            )
            should_store: bool = bool(importance_result.get("should_store", False))

            if should_store:
                await self._call_skill(
                    "store_episodic",
                    {
                        "skill": skill_name,
                        "result_summary": content,
                        "importance_score": importance_result.get("importance_score", 0.5),
                        "topics": importance_result.get("topics", []),
                        "cycle": self._cycle_count,
                    },
                )
                logger.info(
                    "サイクル %d: エピソード記憶保存 skill=%s score=%.2f",
                    self._cycle_count,
                    skill_name,
                    importance_result.get("importance_score", 0.5),
                )

        except Exception as exc:
            logger.warning(
                "サイクル %d: evaluate_importance/store_episodic エラー: %s",
                self._cycle_count,
                exc,
            )

    # ------------------------------------------------------------------
    # Skill 呼び出しのヘルパー
    # ------------------------------------------------------------------

    async def _call_skill(self, skill_name: str, params: dict[str, Any]) -> Any:
        """
        Skill を呼び出すヘルパー。

        skill_registry に登録されていればそのハンドラを呼び出す。
        登録がない場合は NotImplementedError を raise する。

        Args:
            skill_name: 実行する Skill 名
            params: Skill に渡すパラメータ

        Returns:
            Skill の実行結果

        Raises:
            NotImplementedError: skill_registry に未登録の Skill を呼び出した場合
        """
        handler = self._skill_registry.get(skill_name)
        if handler is None:
            raise NotImplementedError(
                f"Skill '{skill_name}' が skill_registry に登録されていません。"
                "AgentLoop の skill_registry に Skill ハンドラを登録してください。"
            )
        return await handler(params)

    # ------------------------------------------------------------------
    # ユーティリティ
    # ------------------------------------------------------------------

    def _get_available_skills(self) -> list[str]:
        """
        実行可能な Skill 名のリストを返す。

        固定リストから取得する。
        """
        return list(_AVAILABLE_SKILL_NAMES)
