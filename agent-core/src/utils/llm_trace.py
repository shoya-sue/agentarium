"""
utils/llm_trace.py — LLM 呼び出しトレースキャプチャ

contextvars.ContextVar を使って、Skill 実行コンテキスト内での
LLM 呼び出し入出力を収集する。

Usage:
    token = llm_events_var.set([])
    try:
        result = await skill.run(params)
        events = llm_events_var.get()  # 収集された LLM 呼び出し履歴
    finally:
        llm_events_var.reset(token)
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

# None = キャプチャ無効、list = キャプチャ有効
llm_events_var: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "llm_events", default=None
)


def record_llm_event(event: dict[str, Any]) -> None:
    """LLM 呼び出しイベントを現在のコンテキストに記録する。"""
    events = llm_events_var.get()
    if events is not None:
        events.append(event)
