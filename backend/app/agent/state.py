# -*- coding: utf-8 -*-
"""ReAct Agent 状态：继承 create_agent 的 AgentState，叠加旅行业务字段。

业务字段由 tool 经 Command(update=...) 写、InjectedState 读，stream 层读出供 SSE。
messages 由 AgentState 提供（add_messages reducer），无需重复声明。
"""
from typing import Annotated

from langchain.agents import AgentState

from app.agent.reducers import merge_xhs_sources


class TripState(AgentState):
    day_plans: list
    changed_days: list
    plan_version: int
    budget_check: dict
    retry_count: int
    summary: str
    # 带 reducer：同一 step 多个 xhs tool 各写增量时由 reducer 合并去重，避免并发写冲突
    xhs_sources: Annotated[list, merge_xhs_sources]
