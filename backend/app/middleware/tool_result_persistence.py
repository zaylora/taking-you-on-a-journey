# -*- coding: utf-8 -*-
"""中间件：大工具结果落盘（横切能力）。"""
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.core.config import get_settings
from app.tools.tool_result_storage import persist_tool_content

_EXCLUDE = frozenset({
    "finalize_plan",
    "compute_budget_tool",
    "read_persisted_tool_result",
    "ask_clarification",
})


class ToolResultPersistenceMiddleware(AgentMiddleware):
    """拦截工具返回，对超阈值结果落盘并替换为轻量 envelope。"""

    def _apply(self, tool_name: str, response: Any) -> Any:
        if tool_name in _EXCLUDE:
            return response
        settings = get_settings()
        persist_kwargs = {
            "tool_name": tool_name,
            "storage_dir": settings.tool_result_storage_dir,
            "threshold_chars": settings.tool_result_persist_threshold_chars,
            "preview_chars": settings.tool_result_preview_chars,
        }
        if isinstance(response, ToolMessage):
            new_content = persist_tool_content(
                response.content,
                tool_call_id=response.tool_call_id or "",
                **persist_kwargs,
            )
            return response if new_content is None else response.model_copy(update={"content": new_content})
        if isinstance(response, Command) and isinstance(response.update, dict):
            messages = response.update.get("messages") or []
            for index, message in enumerate(messages):
                if not isinstance(message, ToolMessage):
                    continue
                new_content = persist_tool_content(
                    message.content,
                    tool_call_id=message.tool_call_id or "",
                    **persist_kwargs,
                )
                if new_content is not None:
                    messages[index] = message.model_copy(update={"content": new_content})
        return response

    def wrap_tool_call(self, request, handler):
        return self._apply(request.tool.name, handler(request))

    async def awrap_tool_call(self, request, handler):
        return self._apply(request.tool.name, await handler(request))
