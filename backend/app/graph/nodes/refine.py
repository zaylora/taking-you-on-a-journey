"""M5 refine node: deterministic local edits on existing day_plans."""
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, Field


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
    if "酒店" in query:
        return "change_hotel"
    if "少" in query or "删" in query or "太赶" in query or "轻松" in query:
        return "relax"
    if "换" in query:
        return "replace"
    if "加" in query:
        return "add"
    return "reorder"


def _relax_day(day_plan: dict) -> dict:
    updated = dict(day_plan)
    items = list(updated.get("items", []) or [])
    removable_indexes = [
        i for i, item in enumerate(items)
        if item.get("type") in ("attraction", "meal") and item.get("name")
    ]
    if removable_indexes:
        items.pop(removable_indexes[-1])
    updated["items"] = items
    return updated


def refine(state: dict) -> dict:
    query = state.get("query", "")
    day_plans = deepcopy(state.get("day_plans", []) or [])
    request = dict(state.get("refine_request", {}) or {})
    target_day = request.get("target_day")
    op = request.get("op") or _infer_op(query)
    changed_days: list[int] = []

    if op in ("relax", "remove") and target_day is not None:
        for idx, day in enumerate(day_plans):
            if day.get("day") == target_day:
                day_plans[idx] = _relax_day(day)
                changed_days = [target_day]
                break

    plan_version = (state.get("plan_version", 0) or 0) + (1 if changed_days else 0)
    return {
        "day_plans": day_plans,
        "refine_request": {
            **request,
            "op": op,
            "target_day": target_day,
            "needs_budget_recheck": True,
        },
        "changed_days": changed_days,
        "plan_version": plan_version,
    }
