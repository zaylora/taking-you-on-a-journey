"""M5 fix refine：async 局部重排，只改 target_day，绝不回全量 itinerary。

op 由 dispatch_agent 用规则解析进 state['refine_request']。本节点按 op 在旧 day_plans 上增量改：
- relax/remove/tighten：删/压缩 target_day 的项。
- reorder：target_day 内 items 倒序（确定性局部调序）。
- change_budget：更新预算上限（day_plans 不变，交 budget 核算）。
- change_hotel：items 不动，标记过夜日交 accommodation 重排。
- change_meal/add/replace：补检索后局部插入/替换（见 Task 5）。
"""
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, Field

from app.tools import amap


class RefineRequest(BaseModel):
    op: Literal["add", "remove", "replace", "relax", "tighten", "change_budget", "change_hotel", "change_meal", "reorder"]
    target_day: int | None = None
    target_item_name: str | None = None
    constraints: dict = Field(default_factory=dict)
    needs_search: bool = False
    needs_budget_recheck: bool = True


def _infer_op(query: str) -> str:
    if "预算" in query:
        return "change_budget"
    if "酒店" in query or "住宿" in query:
        return "change_hotel"
    if any(k in query for k in ("晚餐", "午餐", "餐厅", "吃", "饭")) and "换" in query:
        return "change_meal"
    if any(k in query for k in ("少", "删", "太赶", "轻松")):
        return "relax"
    if "换" in query:
        return "replace"
    if "加" in query:
        return "add"
    return "reorder"


def _find_day(day_plans: list, target_day: int | None) -> int | None:
    if target_day is None:
        return None
    for idx, day in enumerate(day_plans):
        if day.get("day") == target_day:
            return idx
    return None


def _relax_day(day_plan: dict) -> dict:
    updated = dict(day_plan)
    items = list(updated.get("items", []) or [])
    removable = [i for i, it in enumerate(items)
                 if it.get("type") in ("attraction", "meal") and it.get("name")]
    if removable:
        items.pop(removable[-1])
    updated["items"] = items
    return updated


def _reorder_day(day_plan: dict) -> dict:
    updated = dict(day_plan)
    updated["items"] = list(reversed(updated.get("items", []) or []))
    return updated


def _poi_to_item(poi: dict, type_: str) -> dict:
    """高德 POI → PlanItem dict（与 itinerary.PlanItem 字段对齐）。"""
    return {
        "type": type_,
        "name": poi.get("name", ""),
        "poi_id": poi.get("poi_id", ""),
        "location": {"lng": poi.get("lng", 0.0), "lat": poi.get("lat", 0.0)},
        "start": "", "end": "", "indoor": False, "note": "", "cost": 0.0,
    }


def _set_meal(day_plan: dict, new_item: dict) -> dict:
    """替换当天第一个 meal 项；没有则追加。"""
    updated = dict(day_plan)
    items = list(updated.get("items", []) or [])
    for i, it in enumerate(items):
        if it.get("type") == "meal":
            items[i] = new_item
            break
    else:
        items.append(new_item)
    updated["items"] = items
    return updated


def _add_or_replace_attraction(day_plan: dict, new_item: dict, replace: bool) -> dict:
    updated = dict(day_plan)
    items = list(updated.get("items", []) or [])
    if replace:
        for i, it in enumerate(items):
            if it.get("type") == "attraction":
                items[i] = new_item
                break
        else:
            items.append(new_item)
    else:
        items.append(new_item)
    updated["items"] = items
    return updated


def _overnight_days(day_plans: list) -> list:
    days = sorted(d.get("day", 0) for d in day_plans)
    return days[:-1] if len(days) > 1 else days


async def refine(state, config=None) -> dict:
    query = state.get("query", "")
    day_plans = deepcopy(state.get("day_plans", []) or [])
    request = dict(state.get("refine_request", {}) or {})
    op = request.get("op") or _infer_op(query)
    target_day = request.get("target_day")
    constraints = request.get("constraints", {}) or {}
    idx = _find_day(day_plans, target_day)
    changed_days: list[int] = []
    extra: dict = {}

    if op in ("relax", "remove", "tighten") and idx is not None:
        day_plans[idx] = _relax_day(day_plans[idx])
        changed_days = [target_day]
    elif op == "reorder" and idx is not None:
        day_plans[idx] = _reorder_day(day_plans[idx])
        changed_days = [target_day]
    elif op == "change_budget":
        new_budget = constraints.get("budget")
        if new_budget:
            extra["budget"] = float(new_budget)
    elif op == "change_hotel":
        changed_days = _overnight_days(day_plans)  # items 不动，accommodation 重排 hotel
    elif op in ("change_meal", "replace", "add") and idx is not None:
        changed_days = await _apply_search_op(state, day_plans, idx, op, constraints)

    plan_version = (state.get("plan_version", 0) or 0) + (1 if changed_days else 0)
    return {
        **extra,
        "day_plans": day_plans,
        "refine_request": {**request, "op": op, "target_day": target_day},
        "changed_days": changed_days,
        "plan_version": plan_version,
    }


async def _apply_search_op(state, day_plans, idx, op, constraints) -> list:
    """Task 5 实现：补检索后局部插入/替换。Task 4 先占位（不改 items）。"""
    return []
