"""apply：operations 确定性执行器（纯能力函数，不进图）。

- replace_plan：复用 app.itinerary 全量排程链（OR-Tools），不改算法。
- 局部 op（Task 5）：复用 app.graph.nodes.refine 的 _apply_day_op 系列。
- 住宿/预算重算（Task 6）：复用 accommodation / budget.compute_budget。
能力函数一律从原始模块 import，不经 nodes.itinerary re-export。
"""
import os
from copy import deepcopy

from app.core.config import get_settings
from app.core.constants import AROUND_RADIUS_M
from app.graph.nodes.time_budget import DAY_BUDGET, LUNCH_MIN, DINNER_MIN
from app.itinerary.assembler import routes_to_skeleton
from app.itinerary.matrix import distance_matrix
from app.itinerary.opentime import parse_opentime
from app.itinerary.optimizer import solve_vrptw
from app.itinerary.prefilter import select_candidates
from app.itinerary.soft_fill import annotate_soft_fields
from app.graph.nodes.refine import _apply_day_op, _finalize_day, _find_day, _overnight_days
from app.tools import amap


def _distance_cache_path(checkpoint_db_path: str) -> str:
    """根据 checkpoint 数据库路径推导距离缓存路径。"""
    d = os.path.dirname(checkpoint_db_path) or "."
    return os.path.join(d, "distance_cache.sqlite")


async def replace_plan(req: dict, context: dict, state: dict, config=None) -> dict:
    """全量重排：消费 context 的景点/餐饮池，跑 OR-Tools，装配 + LLM 软填。

    返回 {daily_centers, day_plans, dropped_attractions, relax_level}。
    逻辑与原 itinerary() 一致，仅把入参从 state 改为 (req, context)。
    """
    days = req.get("days", 3) or 3
    attractions = context.get("attractions", []) or []
    candidates, dropped_pre = select_candidates(attractions, days)
    if not candidates:
        return {
            "daily_centers": [],
            "day_plans": [],
            "dropped_attractions": dropped_pre,
            "relax_level": 0,
        }

    # 以所有候选景点的质心作为虚拟仓库（depot）
    cx = sum(p["lng"] for p in candidates) / len(candidates)
    cy = sum(p["lat"] for p in candidates) / len(candidates)
    depot = {"name": "__depot__", "poi_id": "__depot__", "lng": cx, "lat": cy, "visit_minutes": 0}
    nodes = [depot] + candidates

    db_path = _distance_cache_path(get_settings().checkpoint_db_path)
    matrix = await distance_matrix(nodes, db_path)

    ratings = [0.0] + [p.get("rating", 3.0) for p in candidates]
    tw = [(0, DAY_BUDGET)] + [parse_opentime(p.get("opentime", ""), DAY_BUDGET) for p in candidates]
    # 每天可用时间扣除午餐和晚餐
    solve_budget = max(1, DAY_BUDGET - (LUNCH_MIN + DINNER_MIN))
    routes, dropped_idx, relax = solve_vrptw(
        matrix, nodes, days, solve_budget, time_windows=tw, ratings=ratings
    )

    # 按每天路线质心搜索附近餐厅，无结果时降级用城市餐厅池
    food_kw = (req.get("preferences") or {}).get("food") or "美食"
    city_pool = context.get("restaurants", []) or []
    rest_pools = []
    for route in routes:
        pts = [candidates[i - 1] for i in route if 1 <= i <= len(candidates)]
        if pts:
            cx2 = sum(p["lng"] for p in pts) / len(pts)
            cy2 = sum(p["lat"] for p in pts) / len(pts)
            pool = await amap.search_around(cx2, cy2, food_kw, "餐饮", AROUND_RADIUS_M) or city_pool
        else:
            pool = city_pool
        rest_pools.append(pool)

    skeleton, centers = routes_to_skeleton(routes, candidates, rest_pools)

    # 软填需要 state 提供 weather/num_people 等；把 context.weather 注入 state 副本供 build_soft_payload 使用
    # build_soft_payload 实际读取：weather、num_people、budget_advice
    soft_state = {
        **state,
        "weather": context.get("weather", {}) or {},
        "days": days,
        "preferences": req.get("preferences", {}) or {},
    }
    day_plans = await annotate_soft_fields(skeleton, soft_state, config)

    # 将求解器丢弃的景点加入 dropped 列表
    dropped_solver = [
        {
            "name": candidates[i - 1].get("name", ""),
            "rating": candidates[i - 1].get("rating", 0.0),
            "reason": "综合距离/时间/评分权衡后未排入",
        }
        for i in dropped_idx
        if 1 <= i <= len(candidates)
    ]
    return {
        "daily_centers": centers,
        "day_plans": day_plans,
        "dropped_attractions": dropped_pre + dropped_solver,
        "relax_level": relax,
    }


async def apply_operations(operations: list[dict], context: dict, state: dict, config=None) -> dict:
    """按序执行 operations，统一收尾 + 诚实回报。住宿/预算重算在 Task 6 接入。"""
    day_plans = deepcopy(state.get("day_plans", []) or [])
    centers = list(state.get("daily_centers", []) or [])
    dropped = list(state.get("dropped_attractions", []) or [])
    relax = state.get("relax_level", 0)
    applied: list[str] = []
    skipped: list[str] = []
    changed: set[int] = set()
    touched: set[int] = set()
    needs_accom = False
    budget_new = None

    for op in operations:
        kind = op.get("op")
        if kind == "answer_only":
            continue
        if kind == "replace_plan":
            req = {**(state.get("normalized_req") or {}), **(op.get("requirements_patch") or {})}
            res = await replace_plan(req, context, state, config)
            day_plans = res["day_plans"]
            centers = res["daily_centers"]
            dropped = res["dropped_attractions"]
            relax = res["relax_level"]
            changed = {d.get("day") for d in day_plans}
            touched = set()   # replace_plan 产出已 finalize（含交通段+center）
            needs_accom = True
            applied.append(f"已重新规划 {len(day_plans)} 天行程")
            continue
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
            needs_accom = True
            for d in days:
                changed.add(d)
            applied.append("酒店偏好已更新，将重排住宿")
            continue
        # 局部按天 op：复用 refine helper
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

    for d in touched:
        i = _find_day(day_plans, d)
        if i is not None:
            day_plans[i] = _finalize_day(day_plans[i])

    needs_budget = any(o.get("op") != "reorder" and o.get("op") != "answer_only" for o in operations)
    plan_version = (state.get("plan_version", 0) or 0) + (1 if changed else 0)
    out: dict = {
        "day_plans": day_plans,
        "daily_centers": centers,
        "dropped_attractions": dropped,
        "relax_level": relax,
        "changed_days": sorted(c for c in changed if c is not None),
        "plan_version": plan_version,
        "applied": applied,
        "skipped": skipped,
        "needs_accommodation": needs_accom,
        "needs_budget_recheck": needs_budget,
    }
    if budget_new is not None:
        out["budget"] = budget_new
    return out
