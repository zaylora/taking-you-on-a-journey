# -*- coding: utf-8 -*-
"""组装全局单 Agent ReAct 图：create_agent + 工具 + 系统提示 + 业务 state。"""
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver

from app.agent.prompt import TRIP_AGENT_SYS
from app.agent.state import TripState
from app.agent.time_context import CurrentTimePromptMiddleware
from app.agent.tools import (
    get_current_time, search_attractions, search_restaurants, get_weather, plan_route,
    assemble_itinerary, assign_hotels, compute_budget_tool, finalize_plan,
    xhs_status, research_xhs_travel_guide, xhs_search_notes, xhs_read_note,
    xhs_note_comments, xhs_hot_notes, xhs_user_profile,
)
from app.llm.factory import build_llm

_TOOLS = [
    get_current_time, search_attractions, search_restaurants, get_weather, plan_route,
    assemble_itinerary, assign_hotels, compute_budget_tool, finalize_plan,
    xhs_status, research_xhs_travel_guide, xhs_search_notes, xhs_read_note,
    xhs_note_comments, xhs_hot_notes, xhs_user_profile,
]

# 用哨兵区分「未传 checkpointer」（默认 MemorySaver）与「显式不要 checkpointer」（None）。
# 后者用于 langgraph dev：平台自带持久化，外挂 checkpointer 会冲突。
_DEFAULT = object()


def build_trip_agent(checkpointer=_DEFAULT):
    if checkpointer is _DEFAULT:
        checkpointer = MemorySaver()
    return create_agent(
        model=build_llm(temperature=0, disable_streaming=False),
        tools=_TOOLS,
        system_prompt=TRIP_AGENT_SYS,
        middleware=[CurrentTimePromptMiddleware()],
        state_schema=TripState,
        checkpointer=checkpointer,
    )
