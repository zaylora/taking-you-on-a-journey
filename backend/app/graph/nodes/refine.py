"""M6 refine：序列循环执行器，无检索 handler，诚实回报。

operations 由 dispatch_agent 解析进 state['refine_request']['operations']。
本节点按序在 day_plans 工作副本上应用一串 ops，统一收尾后返回。

支持（Task 3）：reorder / set_pace / remove_poi / set_budget / set_hotel
待接（Task 4）：add_poi / replace_poi
待接（Task 5）：set_region
"""
from copy import deepcopy

from app.core.constants import AROUND_RADIUS_M
from app.graph.nodes.itinerary import insert_transport, haversine_km
from app.graph.nodes.time_budget import attraction_minutes, day_used_minutes, DAY_BUDGET
from app.tools import amap


def _resolve_selector(items: list[dict], selector: dict | None) -> int | None:
    """按 selector 在 items 里定位一个停靠点的下标；命不中返回 None。"""
    sel = selector or {}
    if sel.get("by", "name") == "name":
        name = (sel.get("name") or "").strip()
        if not name:
            return None
        for i, it in enumerate(items):
            if it.get("type") != "transport" and name in (it.get("name") or ""):
                return i
        return None
    kind = sel.get("kind", "attraction")
    idxs = [i for i, it in enumerate(items) if it.get("type") == kind]
    if not idxs:
        return None
    try:
        return idxs[sel.get("index", -1)]
    except IndexError:
        return None


def _recompute_center(stops: list[dict]) -> dict:
    """当天 center = 非交通停靠点坐标均值。"""
    pts = [it.get("location") or {} for it in stops if it.get("type") != "transport"]
    pts = [p for p in pts if p]
    if not pts:
        return {"lng": 0.0, "lat": 0.0}
    return {"lng": sum(p.get("lng", 0.0) for p in pts) / len(pts),
            "lat": sum(p.get("lat", 0.0) for p in pts) / len(pts)}


def _optimize_stops(stops: list[dict]) -> list[dict]:
    """从首个停靠点起，贪心最近邻重排（按 location 直线距离）。"""
    if len(stops) < 3:
        return list(stops)
    remaining = list(stops)
    order = [remaining.pop(0)]
    while remaining:
        last = order[-1].get("location") or {}
        j = min(range(len(remaining)),
                key=lambda i: haversine_km(remaining[i].get("location") or {}, last))
        order.append(remaining.pop(j))
    return order


def _relax_stops(stops: list[dict]) -> list[dict]:
    """反复删当天最后一个景点/餐饮，直到 day_used_minutes <= DAY_BUDGET（至少删 1 个）。"""
    items = list(stops)
    removed = False
    while items and (day_used_minutes(insert_transport(items)) > DAY_BUDGET or not removed):
        removable = [i for i, it in enumerate(items)
                     if it.get("type") in ("attraction", "meal") and it.get("name")]
        if not removable:
            break
        items.pop(removable[-1])
        removed = True
        if day_used_minutes(insert_transport(items)) <= DAY_BUDGET:
            break
    return items


def _find_day(day_plans: list, target_day: int | None) -> int | None:
    if target_day is None:
        return None
    for idx, day in enumerate(day_plans):
        if day.get("day") == target_day:
            return idx
    return None


def _poi_to_item(poi: dict, type_: str) -> dict:
    """高德 POI → PlanItem dict（与 itinerary.PlanItem 字段对齐）。"""
    item = {
        "type": type_,
        "name": poi.get("name", ""),
        "poi_id": poi.get("poi_id", ""),
        "location": {"lng": poi.get("lng", 0.0), "lat": poi.get("lat", 0.0)},
        "start": "", "end": "", "indoor": False, "note": "", "cost": 0.0,
    }
    if type_ == "attraction":
        item["visit_minutes"] = attraction_minutes({**poi, "type": poi.get("type", "")})
    return item


def _overnight_days(day_plans: list) -> list:
    days = sorted(d.get("day", 0) for d in day_plans)
    return days[:-1] if len(days) > 1 else days


def _finalize_day(day_plan: dict) -> dict:
    """收尾：剥掉旧交通段、按当前停靠点重插交通、重算 center。"""
    dp = dict(day_plan)
    stops = [it for it in (dp.get("items") or []) if it.get("type") != "transport"]
    dp["items"] = insert_transport(stops)
    dp["center"] = _recompute_center(stops)
    return dp


async def _search_insert(state, dp: dict, stops: list[dict], op: dict, replace_idx: int | None) -> str | None:
    """围绕当天 center 检索一个 POI 并插入/替换进 stops。空/失败返回 None。"""
    center = dp.get("center") or {}
    kind = op.get("kind", "attraction")
    poi_type = "餐饮" if kind == "meal" else "风景名胜"
    default_kw = "美食" if kind == "meal" else "热门景点"
    try:
        pois = await amap.search_around(center.get("lng", 0.0), center.get("lat", 0.0),
                                        op.get("query") or default_kw, poi_type, AROUND_RADIUS_M)
    except Exception:  # noqa: BLE001 —— 检索失败降级，不阻断本轮
        return None
    if not pois:
        return None
    used = {it.get("poi_id") for it in stops}
    fresh = next((p for p in pois if p.get("poi_id") not in used), pois[0])
    item = _poi_to_item(fresh, "meal" if kind == "meal" else "attraction")
    if replace_idx is None:
        stops.append(item)
        return f"第{dp.get('day')}天新增{item['name']}"
    stops[replace_idx] = item
    return f"第{dp.get('day')}天已替换为{item['name']}"


async def _apply_day_op(state, day_plan: dict, op: dict) -> tuple[dict, bool, str]:
    """对单天应用一个 op。返回 (更新后的 day_plan(items 为停靠点，未插交通), ok, note)。

    Task 3 接入：reorder / set_pace / remove_poi。
    Task 4 接入：add_poi / replace_poi。Task 5 接入：set_region。
    """
    kind = op.get("op")
    dp = dict(day_plan)
    stops = [it for it in (dp.get("items") or []) if it.get("type") != "transport"]
    day = dp.get("day")

    if kind == "reorder":
        strat = op.get("strategy", "optimize")
        dp["items"] = list(reversed(stops)) if strat == "reverse" else _optimize_stops(stops)
        return dp, True, f"第{day}天顺序已调整"

    if kind == "set_pace":
        new_stops = _relax_stops(stops)
        dp["items"] = new_stops
        if len(new_stops) == len(stops):
            return dp, False, f"第{day}天已无可删减项"
        return dp, True, f"第{day}天已精简{len(stops) - len(new_stops)}项"

    if kind == "remove_poi":
        i = _resolve_selector(stops, op.get("selector"))
        if i is None:
            return dp, False, f"第{day}天未定位到要删除的项"
        removed = stops.pop(i)
        dp["items"] = stops
        return dp, True, f"第{day}天已删除{removed.get('name', '')}"

    if kind == "add_poi":
        note = await _search_insert(state, dp, stops, op, replace_idx=None)
        if note:
            dp["items"] = stops
            return dp, True, note
        return dp, False, f"第{day}天未找到合适候选"

    if kind == "replace_poi":
        i = _resolve_selector(stops, op.get("selector"))
        if i is None:
            return dp, False, f"第{day}天未定位到要替换的项"
        note = await _search_insert(state, dp, stops, op, replace_idx=i)
        if note:
            dp["items"] = stops
            return dp, True, note
        return dp, False, f"第{day}天未找到替换候选"

    return dp, False, f"暂不支持的操作：{kind}"


async def refine(state, config=None) -> dict:
    day_plans = deepcopy(state.get("day_plans", []) or [])
    request = dict(state.get("refine_request", {}) or {})
    operations = list(request.get("operations") or [])
    applied: list[str] = []
    skipped: list[str] = []
    changed: set[int] = set()
    touched: set[int] = set()
    needs_accom = False
    budget_new = None

    for op in operations:
        kind = op.get("op")
        if kind == "set_budget":
            amt = op.get("amount")
            if amt is None:
                skipped.append("预算调整缺少金额，已跳过")
                continue
            budget_new = float(amt)
            applied.append(f"预算改为 {budget_new:.0f}")
            continue
        if kind == "set_hotel":
            days = op.get("days") or _overnight_days(day_plans)
            # items 不变，但过夜日计入 changed，使 plan_version 推进，表示「方案版本前进、待 accommodation 节点重排住宿」
            needs_accom = True
            for d in days:
                changed.add(d)
            applied.append("酒店偏好已更新，将重排住宿")
            continue
        # 按天操作
        day = op.get("day")
        idx = _find_day(day_plans, day)
        if idx is None:
            skipped.append(f"第{day}天未找到，已跳过")
            continue
        dp, ok, note = await _apply_day_op(state, day_plans[idx], op)
        day_plans[idx] = dp
        if ok:
            applied.append(note)
            changed.add(day)
            touched.add(day)
        else:
            skipped.append(note)

    # 每个被结构修改的天：统一重建交通 + 重算 center（一次）
    for d in touched:
        i = _find_day(day_plans, d)
        if i is not None:
            day_plans[i] = _finalize_day(day_plans[i])

    needs_budget = any(o.get("op") != "reorder" for o in operations)
    plan_version = (state.get("plan_version", 0) or 0) + (1 if changed else 0)
    out: dict = {
        "day_plans": day_plans,
        "refine_request": {**request,
                           "needs_budget_recheck": needs_budget,
                           "needs_accommodation": needs_accom},
        "changed_days": sorted(changed),
        "plan_version": plan_version,
        "refine_notes": {"applied": applied, "skipped": skipped},
    }
    if budget_new is not None:
        out["budget"] = budget_new
    return out
