# -*- coding: utf-8 -*-
"""预算核算纯函数（迁自 budget 节点）。口径：cost 人均、hotel.price 整间；limit==0 不限。"""

_MAX_RETRY = 2


def _sum_costs(day_plans: list, num_people: int) -> dict:
    ticket = food = transport = hotel = 0.0
    days_list = sorted(d.get("day", 0) for d in day_plans)
    overnight = set(days_list[:-1]) if len(days_list) > 1 else set()
    for d in day_plans:
        for it in d.get("items", []) or []:
            c = it.get("cost", 0.0) or 0.0
            t = it.get("type", "")
            if t == "attraction":
                ticket += c
            elif t == "meal":
                food += c
            elif t == "transport":
                transport += c
        h = d.get("hotel")
        if h and d.get("day", 0) in overnight:
            hotel += h.get("price", 0.0) or 0.0
    n = max(1, num_people)
    breakdown = {
        "ticket": round(ticket * n, 2),
        "food": round(food * n, 2),
        "transport": round(transport * n, 2),
        "hotel": round(hotel, 2),
    }
    estimated = round(breakdown["ticket"] + breakdown["food"]
                      + breakdown["transport"] + breakdown["hotel"], 2)
    return {"breakdown": breakdown, "estimated": estimated}


def _pick_cut_suggestions(day_plans: list, top: int = 3) -> list:
    items = []
    for d in day_plans:
        for it in d.get("items", []) or []:
            cost = it.get("cost", 0.0) or 0.0
            if it.get("type", "") in ("attraction", "meal") and cost > 0:
                items.append({"day": d.get("day", 0), "type": it.get("type", ""),
                              "name": it.get("name", ""), "cost": round(cost, 2)})
    items.sort(key=lambda x: (-x["cost"], x["day"], x["name"]))
    return items[:top]


def compute_budget(day_plans: list, num_people: int, limit: float, retry_count: int) -> dict:
    """核心纯函数：产出 budget_check、advice(None|dict)、new_retry_count。"""
    sums = _sum_costs(day_plans, num_people)
    estimated = sums["estimated"]
    over = limit > 0 and estimated > limit
    retry = over and retry_count < _MAX_RETRY
    new_count = retry_count + (1 if retry else 0)
    note = ""
    if over and not retry:
        note = f"已尽力压缩，仍超出预算约 ¥{round(estimated - limit)}"
    budget_check = {
        "limit": round(limit, 2), "estimated": estimated, "over": over, "retry": retry,
        "breakdown": sums["breakdown"], "retry_count": new_count, "note": note,
    }
    advice = None
    if retry:
        advice = {"over_amount": round(estimated - limit, 2),
                  "cut_suggestions": _pick_cut_suggestions(day_plans)}
    return {"budget_check": budget_check, "advice": advice, "retry_count": new_count}
