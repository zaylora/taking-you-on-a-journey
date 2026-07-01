# -*- coding: utf-8 -*-
"""中间件：把当前时间快照注入模型 system message。"""
from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain_core.messages import SystemMessage

from app.tools.time_context import build_system_prompt


class CurrentTimePromptMiddleware(AgentMiddleware):
    """把当前时间快照注入每一次模型调用的 system message。"""

    def wrap_model_call(self, request: ModelRequest, handler):
        request = request.override(system_message=SystemMessage(content=build_system_prompt()))
        return handler(request)

    async def awrap_model_call(self, request: ModelRequest, handler):
        request = request.override(system_message=SystemMessage(content=build_system_prompt()))
        return await handler(request)
