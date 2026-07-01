# -*- coding: utf-8 -*-
"""tools 能力域入口：暴露工具对象与注册中心清单。"""
from app.tools.actions import trip
from app.tools.actions import (
    ask_clarification,
    assemble_itinerary,
    assign_hotels,
    compute_budget_tool,
    finalize_plan,
    get_current_time,
    get_weather,
    plan_route,
    read_persisted_tool_result,
    research_xhs_travel_guide,
    search_attractions,
    search_restaurants,
    xhs_hot_notes,
    xhs_note_comments,
    xhs_read_note,
    xhs_search_notes,
    xhs_status,
    xhs_user_profile,
)
from app.tools.registry import ALL_TOOLS

__all__ = [
    "ALL_TOOLS",
    "trip",
    "get_current_time",
    "search_attractions",
    "search_restaurants",
    "get_weather",
    "plan_route",
    "assemble_itinerary",
    "assign_hotels",
    "read_persisted_tool_result",
    "compute_budget_tool",
    "finalize_plan",
    "ask_clarification",
    "xhs_status",
    "research_xhs_travel_guide",
    "xhs_search_notes",
    "xhs_read_note",
    "xhs_note_comments",
    "xhs_hot_notes",
    "xhs_user_profile",
]
