# -*- coding: utf-8 -*-
"""组装全局单 Agent ReAct 图：create_agent + 工具 + 系统提示 + 业务 state。"""
from langchain.agents import create_agent
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    SummarizationMiddleware,
)
from langgraph.checkpoint.memory import MemorySaver

from app.agent.prompt import TRIP_AGENT_SYS, TRIP_SUMMARY_PROMPT
from app.agent.state import TripState
from app.agent.time_context import CurrentTimePromptMiddleware
from app.agent.tools import (
    get_current_time, search_attractions, search_restaurants, get_weather, plan_route,
    assemble_itinerary, assign_hotels, compute_budget_tool, finalize_plan,
)
from app.llm.factory import build_llm

_TOOLS = [
    get_current_time, search_attractions, search_restaurants, get_weather, plan_route,
    assemble_itinerary, assign_hotels, compute_budget_tool, finalize_plan,
]

# 用哨兵区分「未传 checkpointer」（默认 MemorySaver）与「显式不要 checkpointer」（None）。
# 后者用于 langgraph dev：平台自带持久化，外挂 checkpointer 会冲突。
_DEFAULT = object()


def _build_context_middleware():
    """上下文治理：先清旧工具结果，再在长对话时摘要旧消息。"""
    return [
        CurrentTimePromptMiddleware(),
        # 工具输出是旅行规划里最容易膨胀的部分。先清旧工具结果，保留最近
        # 4 个结果支撑当前推理；最终确认和预算结果很短且有业务语义，不清。
        ContextEditingMiddleware(
            edits=[
                ClearToolUsesEdit(
                    trigger=16_000,
                    clear_at_least=5_000,
                    keep=4,
                    exclude_tools=("finalize_plan", "compute_budget_tool"),
                )
            ],
            token_count_method="approximate",
        ),
        # 摘要会损失细节，所以比工具清理更晚触发。保留最近 10k tokens
        # 原文，避免“第二天那个餐厅”这类最近指代被压缩掉。
        SummarizationMiddleware(
            model=build_llm(temperature=0, disable_streaming=True),
            trigger=[{"tokens": 40_000}, {"messages": 28}],
            keep=("tokens", 10_000),
            summary_prompt=TRIP_SUMMARY_PROMPT,
            trim_tokens_to_summarize=16_000,
        ),
    ]


def build_trip_agent(checkpointer=_DEFAULT):
    if checkpointer is _DEFAULT:
        checkpointer = MemorySaver()
    return create_agent(
        model=build_llm(temperature=0, disable_streaming=False),
        tools=_TOOLS,
        system_prompt=TRIP_AGENT_SYS,
        middleware=_build_context_middleware(),
        state_schema=TripState,
        checkpointer=checkpointer,
    )
