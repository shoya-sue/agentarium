"""
main.py — Agentarium agent-core エントリポイント

Phase 1: browse_source → store_episodic / store_semantic パイプラインを
ルールベーススケジューラで実行する。

Phase 2: ENABLE_AGENT_LOOP=true の場合、LLM 駆動の AgentLoop を
PatrolScheduler と並行して起動する。
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from core import SkillEngine
from models.llm import LLMClient
from skills.perception.browse_source import BrowseSourceSkill
from skills.memory.store_episodic import StoreEpisodicSkill
from skills.memory.store_semantic import StoreSemanticSkill
from skills.memory.recall_related import RecallRelatedSkill
from skills.memory.evaluate_importance import EvaluateImportanceSkill
from skills.reasoning.select_skill import SelectSkillSkill
from skills.reasoning.reflect import ReflectSkill
from skills.reasoning.plan_task import PlanTaskSkill
from skills.reasoning.generate_response import GenerateResponseSkill
from skills.reasoning.build_llm_context import BuildLlmContextSkill
from skills.action.send_discord import SendDiscordSkill
from skills.action.post_x import PostXSkill
from skills.action.reply_x import ReplyXSkill
from skills.character.build_persona_context import BuildPersonaContextSkill
from skills.character.update_emotional_state import UpdateEmotionalStateSkill
from skills.character.update_emotion import UpdateEmotionSkill
from skills.character.update_character_state import UpdateCharacterStateSkill
from skills.character.maintain_presence import MaintainPresenceSkill
from skills.memory.compress_memory import CompressMemorySkill
from skills.memory.forget_low_value import ForgetLowValueSkill
from skills.reasoning.generate_goal import GenerateGoalSkill
from skills.output.generate_daily_digest import GenerateDailyDigestSkill
from skills.output.generate_topic_report import GenerateTopicReportSkill
from skills.output.generate_trend_alert import GenerateTrendAlertSkill
from utils.config import load_yaml_config

# ──────────────────────────────────────────────
# ディレクトリ設定（実行ディレクトリ基準）
# ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent  # /app（コンテナ内: /app/src/main.py）
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
TRACES_DIR = DATA_DIR / "traces"


def _setup_logging(level: str = "INFO") -> None:
    """ロギング設定"""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        stream=sys.stdout,
    )


async def build_engine(settings: dict) -> SkillEngine:
    """設定から SkillEngine を構築して Skill を登録する"""
    TRACES_DIR.mkdir(parents=True, exist_ok=True)

    engine = SkillEngine(
        config_base=CONFIG_DIR,
        traces_dir=TRACES_DIR,
    )

    # --- LLM クライアント ---
    ollama_cfg = settings.get("ollama", {})
    llm = LLMClient(
        base_url=ollama_cfg.get("base_url", "http://localhost:11434"),
        model=ollama_cfg.get("default_model", "qwen3.5:35b-a3b"),
        timeout_seconds=int(ollama_cfg.get("timeout_seconds", 30)),
    )

    # --- Qdrant 設定 ---
    qdrant_cfg = settings.get("qdrant", {})
    qdrant_host = qdrant_cfg.get("host", "localhost")
    qdrant_port = int(qdrant_cfg.get("port", 6333))

    # --- 埋め込みサーバー設定 ---
    routing_cfg = load_yaml_config(CONFIG_DIR / "llm" / "routing.yaml")
    embed_cfg = routing_cfg.get("embedding_server", {})
    embed_url = embed_cfg.get("local_url", "http://localhost:8001")

    # --- Skill 登録 ---
    browse_source = BrowseSourceSkill(config_dir=CONFIG_DIR)
    engine.register(
        "browse_source",
        browse_source.run,
        spec_path=CONFIG_DIR / "skills" / "perception" / "browse_source.yaml",
    )

    store_episodic = StoreEpisodicSkill(
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
    )
    engine.register(
        "store_episodic",
        store_episodic.run,
        spec_path=CONFIG_DIR / "skills" / "memory" / "store_episodic.yaml",
    )

    store_semantic = StoreSemanticSkill(
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        embed_url=embed_url,
        llm_client=llm,
    )
    engine.register(
        "store_semantic",
        store_semantic.run,
        spec_path=CONFIG_DIR / "skills" / "memory" / "store_semantic.yaml",
    )

    return engine


async def run_once(engine: SkillEngine, source_id: str, max_items: int = 20) -> None:
    """
    1 回の情報収集→記憶パイプラインを実行する。

    browse_source → store_episodic / store_semantic
    """
    logger = logging.getLogger(__name__)
    logger.info("=== パイプライン開始: %s ===", source_id)

    # 1. 情報収集
    import time
    t_start = time.monotonic()
    items: list[dict] = await engine.run(
        "browse_source",
        {"source_id": source_id, "max_items": max_items},
    )
    duration_ms = int((time.monotonic() - t_start) * 1000)

    # 2. 実行ログを episodic に保存
    await engine.run(
        "store_episodic",
        {
            "skill": "browse_source",
            "source": source_id,
            "result_count": len(items),
            "duration_ms": duration_ms,
            "error": None,
        },
    )

    # 3. 各アイテムを semantic に保存
    stored_count = 0
    for item in items:
        content = item.get("content") or item.get("title", "")
        if not content:
            continue
        await engine.run(
            "store_semantic",
            {
                "content": content,
                "source_url": item.get("url", ""),
                "title": item.get("title", ""),
            },
        )
        stored_count += 1

    logger.info(
        "=== パイプライン完了: %s — %d 件収集 / %d 件保存 ===",
        source_id,
        len(items),
        stored_count,
    )


async def _run_patrol_scheduler(engine: SkillEngine) -> None:
    """
    Phase 1 PatrolScheduler を実行する非同期タスク。

    エラーが発生してもログに記録してタスクを継続する。
    """
    logger = logging.getLogger(__name__)
    from scheduler.patrol_scheduler import PatrolScheduler

    async def patrol_handler(source_id: str) -> list[dict]:
        """PatrolScheduler から呼び出されるハンドラ。"""
        return await engine.run("browse_source", {"source_id": source_id, "max_items": 20})

    scheduler = PatrolScheduler(
        config_dir=CONFIG_DIR,
        handler=patrol_handler,
    )
    try:
        await scheduler.start()
        # PatrolScheduler.start() は非ブロッキングなので、ここで待機ループを回す
        while True:
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        logger.info("PatrolScheduler タスクがキャンセルされました")
        await scheduler.stop()
        raise
    except Exception as exc:
        logger.error("PatrolScheduler でエラー: %s", exc)
        await scheduler.stop()


async def _run_agent_loop(settings: dict) -> None:
    """
    Phase 2 AgentLoop を実行する非同期タスク。

    ENABLE_AGENT_LOOP=true の場合のみ呼び出す。
    エラーが発生してもログに記録してタスクを継続する。
    """
    logger = logging.getLogger(__name__)
    from scheduler.agent_loop import AgentLoop

    # AgentLoop の設定（settings.yaml または環境変数から取得）
    agent_cfg = settings.get("agent", {})
    character_name: str = agent_cfg.get("character_name", "agent_character")
    cycle_interval: float = float(agent_cfg.get("agent_loop_interval_seconds", 60.0))

    # --- Phase 2 Skill インスタンス生成 ---
    ollama_cfg = settings.get("ollama", {})
    llm = LLMClient(
        base_url=ollama_cfg.get("base_url", "http://localhost:11434"),
        model=ollama_cfg.get("default_model", "qwen3.5:35b-a3b"),
        timeout_seconds=int(ollama_cfg.get("timeout_seconds", 30)),
    )

    qdrant_cfg = settings.get("qdrant", {})
    qdrant_host = qdrant_cfg.get("host", "localhost")
    qdrant_port = int(qdrant_cfg.get("port", 6333))

    routing_cfg = load_yaml_config(CONFIG_DIR / "llm" / "routing.yaml")
    embed_url = routing_cfg.get("embedding_server", {}).get("local_url", "http://localhost:8001")

    # キャラクタースキル
    build_persona_context = BuildPersonaContextSkill(config_dir=CONFIG_DIR)
    update_emotional_state = UpdateEmotionalStateSkill(
        llm_client=llm,
        config_dir=CONFIG_DIR,
    )

    # 記憶スキル
    store_episodic = StoreEpisodicSkill(
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
    )
    store_semantic = StoreSemanticSkill(
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        embed_url=embed_url,
        llm_client=llm,
    )
    recall_related = RecallRelatedSkill(
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        embed_url=embed_url,
    )
    evaluate_importance = EvaluateImportanceSkill(llm_client=llm)

    # 推論スキル
    select_skill = SelectSkillSkill(llm_client=llm, config_dir=CONFIG_DIR)
    reflect = ReflectSkill(llm_client=llm, config_dir=CONFIG_DIR)
    plan_task = PlanTaskSkill(llm_client=llm, config_dir=CONFIG_DIR)
    generate_response = GenerateResponseSkill(llm_client=llm, config_dir=CONFIG_DIR)
    build_llm_context = BuildLlmContextSkill(config_dir=CONFIG_DIR)

    # アクションスキル
    send_discord = SendDiscordSkill(config_dir=CONFIG_DIR)
    post_x = PostXSkill()
    reply_x = ReplyXSkill()

    # キャラクタースキル（Phase 3）
    update_emotion = UpdateEmotionSkill()
    update_character_state = UpdateCharacterStateSkill()
    maintain_presence = MaintainPresenceSkill()

    # 記憶スキル（Phase 3）
    from qdrant_client import QdrantClient as _QdrantClient
    _qdrant_client = _QdrantClient(host=qdrant_host, port=qdrant_port)
    compress_memory = CompressMemorySkill(qdrant_client=_qdrant_client)
    forget_low_value = ForgetLowValueSkill(qdrant_client=_qdrant_client)

    # 推論スキル（Phase 3）
    generate_goal = GenerateGoalSkill(llm_client=llm, config_dir=CONFIG_DIR)

    # アウトプットスキル（Phase 3）
    generate_daily_digest = GenerateDailyDigestSkill(llm_client=llm)
    generate_topic_report = GenerateTopicReportSkill(llm_client=llm)
    generate_trend_alert = GenerateTrendAlertSkill(llm_client=llm)

    # browse_source ラッパー（AgentLoop から各フィードを個別スキルとして選択可能にする）
    browse_source_skill = BrowseSourceSkill(config_dir=CONFIG_DIR)

    async def _fetch_hacker_news(params: dict) -> list:
        return await browse_source_skill.run({"source_id": "hacker_news", "max_items": params.get("max_items", 20)})

    async def _fetch_rss(params: dict) -> list:
        return await browse_source_skill.run({"source_id": "rss_feeds", "max_items": params.get("max_items", 20)})

    async def _fetch_github_trending(params: dict) -> list:
        return await browse_source_skill.run({"source_id": "github_trending", "max_items": params.get("max_items", 20)})

    skill_registry = {
        # 情報取得
        "fetch_hacker_news": _fetch_hacker_news,
        "fetch_rss": _fetch_rss,
        "fetch_github_trending": _fetch_github_trending,
        # 記憶
        "store_episodic": store_episodic.run,
        "store_semantic": store_semantic.run,
        "recall_related": recall_related.run,
        "evaluate_importance": evaluate_importance.run,
        # 推論
        "select_skill": select_skill.run,
        "reflect": reflect.run,
        "plan_task": plan_task.run,
        "generate_response": generate_response.run,
        "build_llm_context": build_llm_context.run,
        # キャラクター
        "build_persona_context": build_persona_context.run,
        "update_emotional_state": update_emotional_state.run,
        "update_emotion": update_emotion.run,
        "update_character_state": update_character_state.run,
        "maintain_presence": maintain_presence.run,
        # アクション
        "send_discord": send_discord.run,
        "post_x": post_x.run,
        "reply_x": reply_x.run,
        # 記憶（Phase 3）
        "compress_memory": compress_memory.run,
        "forget_low_value": forget_low_value.run,
        # 推論（Phase 3）
        "generate_goal": generate_goal.run,
        # アウトプット（Phase 3）
        "generate_daily_digest": generate_daily_digest.run,
        "generate_topic_report": generate_topic_report.run,
        "generate_trend_alert": generate_trend_alert.run,
    }

    loop = AgentLoop(
        character_name=character_name,
        cycle_interval_seconds=cycle_interval,
        config_dir=CONFIG_DIR,
        skill_registry=skill_registry,
    )

    try:
        await loop.start()
    except asyncio.CancelledError:
        logger.info("AgentLoop タスクがキャンセルされました")
        await loop.stop()
        raise
    except Exception as exc:
        logger.error("AgentLoop でエラー: %s", exc)
        await loop.stop()


async def main() -> None:
    """メインエントリポイント"""
    settings = load_yaml_config(CONFIG_DIR / "settings.yaml")
    _setup_logging(settings.get("agent", {}).get("log_level", "INFO"))

    logger = logging.getLogger(__name__)

    # Phase 2 AgentLoop の有効フラグ（環境変数で制御、デフォルト: false）
    enable_agent_loop: bool = os.environ.get("ENABLE_AGENT_LOOP", "false").lower() == "true"

    if enable_agent_loop:
        logger.info("Agentarium agent-core 起動 (Phase 2: PatrolScheduler + AgentLoop)")
    else:
        logger.info("Agentarium agent-core 起動 (Phase 1: PatrolScheduler のみ)")

    engine = await build_engine(settings)

    # Phase 1: PatrolScheduler タスクを作成
    tasks = [asyncio.create_task(_run_patrol_scheduler(engine), name="patrol_scheduler")]

    # Phase 2: ENABLE_AGENT_LOOP=true の場合のみ AgentLoop を追加
    if enable_agent_loop:
        tasks.append(asyncio.create_task(_run_agent_loop(settings), name="agent_loop"))

    try:
        # どちらかのタスクが失敗してももう一方は継続する
        await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        logger.info("メインタスクがキャンセルされました")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        logger.info("Agentarium agent-core 終了")


if __name__ == "__main__":
    asyncio.run(main())
