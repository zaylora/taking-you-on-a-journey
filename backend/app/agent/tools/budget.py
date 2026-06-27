# -*- coding: utf-8 -*-
"""Budget and finalization Agent tools."""
import json
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.agent.itinerary.budgeting import compute_budget
from app.agent.itinerary.diffing import diff_changed_days


@tool
async def compute_budget_tool(day_plans: list, num_people: int = 1, limit: float = 0.0,
                              tool_call_id: Annotated[str, InjectedToolCallId] = "",
                              state: Annotated[dict, InjectedState] = None) -> Command:
    """核算行程总花费并判定是否超预算：把 budget_check 写回 state（供前端预算条展示）、累计 retry_count，
    并回传 {budget_check, cut_suggestions} 供你查看。超支时 cut_suggestions 给出可削减的高价项；
    是否重排由你（agent）自主决定。"""
    retry_count = (state or {}).get("retry_count", 0) or 0
    res = compute_budget(day_plans, max(1, num_people), limit or 0.0, retry_count)
    advice = res["advice"] or {}
    budget_check = res["budget_check"]
    summary = {"budget_check": budget_check, "cut_suggestions": advice.get("cut_suggestions", [])}
    return Command(update={
        "budget_check": budget_check,
        "retry_count": res["retry_count"],
        "messages": [ToolMessage(
            json.dumps(summary, ensure_ascii=False), tool_call_id=tool_call_id)],
    })


@tool
async def finalize_plan(day_plans: list,
                        tool_call_id: Annotated[str, InjectedToolCallId],
                        state: Annotated[dict, InjectedState] = None) -> Command:
    """确认最终行程：写入 day_plans，并自动算出本轮变更的 changed_days 供前端增量重绘。
    完成规划或修改后调用一次。"""
    old = (state or {}).get("day_plans", []) or []
    changed = diff_changed_days(old, day_plans)
    old_ver = (state or {}).get("plan_version", 0) or 0
    new_ver = old_ver + (1 if changed else 0)
    return Command(update={
        "day_plans": day_plans,
        "changed_days": changed,
        "plan_version": new_ver,
        "messages": [ToolMessage(
            f"已确认行程，变更天数 {changed or '无'}", tool_call_id=tool_call_id)],
    })
