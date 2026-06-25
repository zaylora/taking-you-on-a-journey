# -*- coding: utf-8 -*-
"""组装全局单 Agent ReAct 图：create_agent + 9 工具 + 系统提示 + 业务 state。"""
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver

from app.agent.prompt import TRIP_AGENT_SYS
from app.agent.state import TripState
from app.agent.tools import (
    search_attractions, search_restaurants, get_weather, plan_route,
    assemble_itinerary, assign_hotels, compute_budget_tool, ask_user, finalize_plan,
)
from app.llm.factory import build_llm

_TOOLS = [
    search_attractions, search_restaurants, get_weather, plan_route,
    assemble_itinerary, assign_hotels, compute_budget_tool, ask_user, finalize_plan,
]


def build_trip_agent(checkpointer=None):
    return create_agent(
        model=build_llm(temperature=0, disable_streaming=False),
        tools=_TOOLS,
        system_prompt=TRIP_AGENT_SYS,
        state_schema=TripState,
        checkpointer=checkpointer or MemorySaver(),
    )
