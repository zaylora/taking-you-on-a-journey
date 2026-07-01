# -*- coding: utf-8 -*-
"""工具注册中心：集中声明所有 @tool，统一暴露给 agent 组装。"""
from app.tools.actions.budget import compute_budget_tool, finalize_plan
from app.tools.actions.clarify import ask_clarification
from app.tools.actions.itinerary import assemble_itinerary
from app.tools.actions.lodging import assign_hotels
from app.tools.actions.persisted_result import read_persisted_tool_result
from app.tools.actions.time import get_current_time
from app.tools.actions.trip import (
    get_weather, plan_route, search_attractions, search_restaurants,
)
from app.tools.actions.xhs import (
    research_xhs_travel_guide, xhs_hot_notes, xhs_note_comments, xhs_read_note,
    xhs_search_notes, xhs_status, xhs_user_profile,
)

ALL_TOOLS = [
    get_current_time, search_attractions, search_restaurants, get_weather, plan_route,
    assemble_itinerary, assign_hotels, compute_budget_tool, finalize_plan,
    ask_clarification, read_persisted_tool_result,
    xhs_status, research_xhs_travel_guide, xhs_search_notes, xhs_read_note,
    xhs_note_comments, xhs_hot_notes, xhs_user_profile,
]
