"""M5 fix 按需重排路由（规则，不调 LLM）。

对应架构图两个判断菱形：
- route_after_plan：itinerary(plan_new) / refine 出口 → 是否重排酒店 / 是否重算预算 / 都不需。
- route_after_accommodation：分配完酒店后 → 是否重算预算。
依据 state 里的 last_intent + refine_request（dispatch_agent/refine 已写）。
"""


def route_after_plan(state: dict) -> str:
    if (state.get("last_intent") or "plan_new") == "plan_new":
        return "accommodation"
    req = state.get("refine_request", {}) or {}
    if req.get("op") == "change_hotel":
        return "accommodation"
    if req.get("needs_budget_recheck"):
        return "budget"
    return "summarize"


def route_after_accommodation(state: dict) -> str:
    if (state.get("last_intent") or "plan_new") == "plan_new":
        return "budget"
    return "budget" if (state.get("refine_request", {}) or {}).get("needs_budget_recheck") else "summarize"
