# -*- coding: utf-8 -*-
"""澄清类 Agent tool：把缺口问题结构化写回 state，交由 SSE 层展示。"""
import json
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command


_MAX_OPTIONS = 4


def _normalize_options(options: list[str] | None) -> list[str]:
    normalized = []
    for option in options or []:
        text = str(option).strip()
        if text:
            normalized.append(text)
        if len(normalized) >= _MAX_OPTIONS:
            break
    return normalized


@tool
async def ask_clarification(
    field: str,
    question: str,
    options: list[str] | None = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """当缺少关键旅行条件时提问：写入 clarification_request，由前端渲染选项或自由输入。"""
    request = {
        "field": str(field or "").strip(),
        "question": str(question or "").strip(),
        "options": _normalize_options(options),
    }
    return Command(update={
        "clarification_request": request,
        "messages": [ToolMessage(
            json.dumps(request, ensure_ascii=False),
            tool_call_id=tool_call_id,
        )],
    })
