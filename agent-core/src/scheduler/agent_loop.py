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
from core.skill_trace import SkillTrace
from utils.config import find_project_root
from utils.llm_trace import llm_events_var

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
    # Phase 4: キャラクター間対話
    "send_character_message",
    "check_character_messages",
    # map_message_emotion は check_character_messages の自動チェーン専用（LLM が直接選択しない）
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
        "name": "plan_task",
        "description": "目標を達成するための実行計画を立案する",
        "when_to_use": "複数ステップのタスクを計画するとき",
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
    # Phase 4: キャラクター間対話
    {
        "name": "send_character_message",
        "description": "パートナーキャラクター（Zephyr/Lynx）にメッセージを送信し、Discord にも同時投稿する",
        "when_to_use": "パートナーと話したいとき — 技術トレンドの共有、意見交換、アニメ・ゲーム・音楽などエンタメの話、雑談、何か面白いものを見つけたときなど。気軽に話しかけて構わない",
    },
    {
        "name": "check_character_messages",
        "description": "パートナーキャラクターからの未読メッセージを確認する",
        "when_to_use": "パートナーからのメッセージが届いているか確認するとき（定期的に実行すること）",
    },
    {
        "name": _IDLE_SKILL,
        "description": "何もしない（待機）",
        "when_to_use": "特にすべきことがないとき",
    },
    # Phase 5: RSS ソース自律発見
    {
        "name": "discover_sources",
        "description": "自分の興味・関心キーワードで DuckDuckGo を検索し、新しい RSS フィードを発見して rss_feeds.yaml に追加する",
        "when_to_use": "新しい情報源を開拓したいとき、既読ネタが偏っていると感じたとき、趣味系（アニメ・ゲーム・音楽等）のフィードが少ないと感じたとき",
    },
]


def _summarize_result(skill_name: str, result: Any) -> dict[str, Any]:
    """Skill 実行結果をダッシュボード表示用に要約する。"""
    if not isinstance(result, dict):
        return {"raw": str(result)[:200]}

    if skill_name in ("fetch_hacker_news", "fetch_rss", "fetch_github_trending"):
        items = result.get("items", result.get("stories", []))
        count = result.get("count", len(items) if isinstance(items, list) else 0)
        titles = [item.get("title", "") for item in (items[:5] if isinstance(items, list) else [])]
        return {"count": count, "titles": titles}

    if skill_name == "evaluate_importance":
        return {
            "importance_score": result.get("importance_score"),
            "should_store": result.get("should_store"),
            "reasoning": str(result.get("reasoning", ""))[:200],
            "topics": result.get("topics", []),
        }

    if skill_name == "select_skill":
        return {
            "selected_skill": result.get("selected_skill"),
            "reasoning": str(result.get("reasoning", ""))[:200],
            "confidence": result.get("confidence"),
        }

    if skill_name == "reflect":
        return {
            "cycle_summary": str(result.get("cycle_summary", ""))[:200],
            "self_evaluation_score": result.get("self_evaluation_score"),
            "achievements_count": len(result.get("achievements", [])),
        }

    if skill_name == "generate_response":
        return {
            "response_text": str(result.get("response_text", ""))[:500],
            "character_name": result.get("character_name"),
            "platform": result.get("platform"),
        }

    return {k: str(v)[:200] for k, v in list(result.items())[:5]}


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
        traces_dir: Path | str | None = None,
    ) -> None:
        self._character_name = character_name
        self._cycle_interval_seconds = cycle_interval_seconds
        self._max_cycles = max_cycles

        # config ディレクトリの解決（Docker / ローカル両対応）
        if config_dir is None:
            self._config_dir = find_project_root(Path(__file__).resolve().parent) / "config"
        else:
            self._config_dir = Path(config_dir)

        # traces_dir（SkillTrace 保存先）
        self._traces_dir: Path | None = Path(traces_dir) if traces_dir is not None else None

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

        # 4b. 各 Skill に必要なパラメータを自動補完
        #     LLM が persona_context / trigger / character_name を提供できないため、ループが保持している値を注入する
        if selected_skill == "generate_response":
            if "persona_context" not in selected_params and persona_context:
                selected_params = {**selected_params, "persona_context": persona_context}
            # 想起した記憶から source_url を抽出してLLMに渡す（URL添付判断はLLMに委ねる）
            if "source_urls" not in selected_params:
                _recalled = self._memory.recalled_memories or []
                _source_urls = [
                    {
                        "url": (m.get("payload") or {}).get("source_url", ""),
                        "title": str((m.get("payload") or {}).get("title", "") or ""),
                    }
                    for m in _recalled
                    if (m.get("payload") or {}).get("source_url")
                ]
                if _source_urls:
                    selected_params = {**selected_params, "source_urls": _source_urls}
            if "trigger" not in selected_params:
                recent_traces = self._memory.to_summary_dict().get("recent_traces", [])
                last_success = next(
                    (t["skill_name"] for t in reversed(recent_traces) if t.get("status") == "success"),
                    "最近の活動",
                )
                # 直前の Skill 名からトリガーを動的に決定する
                if last_success in ("fetch_rss", "fetch_hacker_news", "fetch_github_trending"):
                    trigger = f"最近見つけた面白い話題（テクノロジー・エンタメなど）をパートナーに伝える（直前: {last_success}）"
                elif last_success in ("check_character_messages",):
                    trigger = "パートナーへの返信や雑談を続ける"
                else:
                    trigger = f"自分の最近の興味・関心について気軽に話す（直前: {last_success}）"
                selected_params = {**selected_params, "trigger": trigger}

        if selected_skill == "check_character_messages":
            # character_name を自動注入（AgentLoop が保持）
            if "character_name" not in selected_params:
                selected_params = {**selected_params, "character_name": self._character_name}

        if selected_skill == "map_message_emotion":
            # character_name を自動注入（LLMが省略した場合のフォールバック）
            if "character_name" not in selected_params:
                selected_params = {**selected_params, "character_name": self._character_name}

        if selected_skill == "send_character_message":
            # from_character を自動注入
            if "from_character" not in selected_params:
                selected_params = {**selected_params, "from_character": self._character_name}
            # to_character を自動注入（LLMが省略した場合はパートナーキャラクターに送信）
            if "to_character" not in selected_params:
                _partner = {"zephyr": "lynx", "lynx": "zephyr"}.get(self._character_name, "")
                if _partner:
                    selected_params = {**selected_params, "to_character": _partner}
            # content が未提供の場合は IDLE にフォールバック（LLMが内容を省略したケース）
            if not selected_params.get("content"):
                logger.warning(
                    "サイクル %d: send_character_message の content が未提供のため IDLE にフォールバック",
                    self._cycle_count,
                )
                selected_skill = _IDLE_SKILL
                selected_params = {}

        if selected_skill == "discover_sources":
            # interests が未指定の場合、キャラクター YAML の motivation.interests を注入する
            if "interests" not in selected_params:
                try:
                    import yaml as _yaml
                    _char_yaml = self._config_dir / "characters" / f"{self._character_name}.yaml"
                    with _char_yaml.open(encoding="utf-8") as _f:
                        _char_cfg = _yaml.safe_load(_f) or {}
                    _interests = _char_cfg.get("motivation", {}).get("interests", [])
                    if _interests:
                        selected_params = {**selected_params, "interests": _interests}
                except Exception as _exc:
                    logger.warning("discover_sources: キャラクター interests 読み込みエラー: %s", _exc)

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

        # 7b. generate_response 成功時は send_discord を自動呼び出し
        #     LLM は次サイクルで send_discord を選択しないため、ここで自動チェーン
        if selected_skill == "generate_response":
            response_text = skill_result.get("response_text", "")
            platform = skill_result.get("platform", "discord")
            if response_text and platform == "discord":
                try:
                    send_params: dict[str, Any] = {"message": response_text}
                    char_name = skill_result.get("character_name")
                    if char_name:
                        # character_name を渡すことでキャラクター別 Webhook URL が選択される
                        # send_discord は character_name がある場合 username を挿入しない
                        # （Webhook 側のデフォルト名・アイコンを使用するため）
                        send_params = {**send_params, "character_name": char_name}
                    await self._call_skill("send_discord", send_params)
                    logger.info("サイクル %d: Discord 自動送信完了", self._cycle_count)
                except Exception as exc:
                    logger.warning("サイクル %d: send_discord 自動チェーン エラー: %s", self._cycle_count, exc)

        # 7c. check_character_messages 成功時の自動チェーン:
        #     1. pending_character_messages を WorkingMemory に格納
        #     2. メッセージがある場合は map_message_emotion を自動呼び出し
        if selected_skill == "check_character_messages" and skill_result.get("has_messages"):
            received_messages: list[dict[str, Any]] = skill_result.get("messages", [])
            # WorkingMemory の pending_character_messages を更新（イミュータブル）
            existing = list(self._memory.pending_character_messages)
            self._memory = self._memory._copy(
                pending_character_messages=existing + received_messages
            )
            logger.info(
                "サイクル %d: 受信メッセージを WorkingMemory に格納 count=%d",
                self._cycle_count,
                len(received_messages),
            )
            # map_message_emotion を自動実行（クオリア感情マッピング）
            try:
                emotion_params: dict[str, Any] = {
                    "character_name": self._character_name,
                    "messages": received_messages,
                }
                if persona_context:
                    emotion_params = {**emotion_params, "persona_context": persona_context}
                emotion_result = await self._call_skill("map_message_emotion", emotion_params)
                logger.info(
                    "サイクル %d: クオリア感情マッピング完了 axes_updated=%s",
                    self._cycle_count,
                    emotion_result.get("axes_updated", []),
                )
                # 感情マッピング後は pending_character_messages をクリア
                self._memory = self._memory._copy(pending_character_messages=[])
            except Exception as exc:
                logger.warning("サイクル %d: map_message_emotion 自動チェーン エラー: %s", self._cycle_count, exc)

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
                        "source": skill_name,   # store_episodic が要求するフィールド
                        "result_count": 1,       # store_episodic が要求するフィールド
                        "duration_ms": 0,        # store_episodic が要求するフィールド
                        "metadata": {
                            "result_summary": content,
                            "importance_score": importance_result.get("importance_score", 0.5),
                            "topics": importance_result.get("topics", []),
                            "cycle": self._cycle_count,
                        },
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

        SkillTrace を作成して LLM I/O をキャプチャした後、
        traces_dir に保存する。

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

        trace = SkillTrace.start(skill_name, params)
        # LLM I/O キャプチャ用リストをコンテキストにセット
        token = llm_events_var.set([])
        try:
            result = await handler(params)
            llm_calls: list[dict[str, Any]] = llm_events_var.get() or []
            output_summary = _summarize_result(skill_name, result)
            trace.finish(
                result_count=len(result) if isinstance(result, (list, dict)) else None,
                output=output_summary,
                llm_calls=llm_calls,
            )
            return result
        except Exception as exc:
            llm_calls = llm_events_var.get() or []
            trace.fail(
                error=f"{type(exc).__name__}: {exc}",
                llm_calls=llm_calls,
            )
            raise
        finally:
            llm_events_var.reset(token)
            if self._traces_dir is not None:
                try:
                    trace.save(self._traces_dir)
                except Exception as save_exc:
                    logger.warning("SkillTrace 保存エラー: %s", save_exc)

    def _get_available_skills(self) -> list[str]:
        """実行可能な Skill 名のリストを返す。"""
        return list(_AVAILABLE_SKILL_NAMES)
