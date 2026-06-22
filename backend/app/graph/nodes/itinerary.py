# -*- coding: utf-8 -*-
"""itinerary 节点：prefilter → 距离矩阵 → OR-Tools VRPTW 求解 → 装配 → LLM 软填。

算法主导几何（选点/分天/顺路/时间窗由 OR-Tools 联合求解，距离用高德真实街道时间），
LLM 只填软字段。取代 m6 的两段贪心（评分预选 + KMeans 聚类 + 预算再平衡 + 最近邻顺路）。
"""
import os

from app.core.config import get_settings
from app.core.constants import AROUND_RADIUS_M
from app.graph.nodes.time_budget import DAY_BUDGET, LUNCH_MIN, DINNER_MIN
from app.itinerary.prefilter import select_candidates
from app.itinerary.matrix import distance_matrix
from app.itinerary.optimizer import solve_vrptw
from app.itinerary.assembler import routes_to_skeleton
from app.itinerary.opentime import parse_opentime
from app.tools import amap

# —— re-export：下游 refine/accommodation/answer/tests 依赖这些符号的旧路径 ——
from app.itinerary.geometry import (  # noqa: F401
    haversine_km, mode_by_distance, pick_nearest, build_day_stops,
    default_cost_by_mode, insert_transport,
)
from app.itinerary.schemas import (  # noqa: F401
    Location, DayWeather, PlanItem, Hotel, DayPlan, DayPlans,
)
from app.itinerary.soft_fill import (  # noqa: F401
    merge_soft_fields, build_soft_payload, annotate_soft_fields,
)
# re-export _build_payload 旧名（纯函数测试依赖旧路径）
from app.itinerary.soft_fill import build_soft_payload as _build_payload  # noqa: F401


def _distance_cache_path(checkpoint_db_path: str) -> str:
    """由 checkpoint 库路径派生同目录下独立的距离缓存库文件名。"""
    d = os.path.dirname(checkpoint_db_path) or "."
    return os.path.join(d, "distance_cache.sqlite")


async def itinerary(state, config) -> dict:
    days = state.get("days", 3) or 3
    attractions = state.get("attractions", []) or []
    candidates, dropped_pre = select_candidates(attractions, days)

    if not candidates:
        return {"daily_centers": [], "day_plans": [], "dropped_attractions": dropped_pre,
                "plan_version": (state.get("plan_version", 0) or 0) + 1, "changed_days": [],
                "relax_level": 0}

    # depot = 候选质心
    cx = sum(p["lng"] for p in candidates) / len(candidates)
    cy = sum(p["lat"] for p in candidates) / len(candidates)
    depot = {"name": "__depot__", "poi_id": "__depot__", "lng": cx, "lat": cy, "visit_minutes": 0}
    nodes = [depot] + candidates

    # 距离缓存用独立 SQLite 文件（与 checkpoints 同目录、不同文件），
    # 避免与 langgraph checkpointer 共用文件时的 "database is locked" 写锁冲突。
    db_path = _distance_cache_path(get_settings().checkpoint_db_path)
    matrix = await distance_matrix(nodes, db_path)

    ratings = [0.0] + [p.get("rating", 3.0) for p in candidates]
    tw = [(0, DAY_BUDGET)] + [parse_opentime(p.get("opentime", ""), DAY_BUDGET)
                              for p in candidates]
    # 求解预算扣除每日餐饮预留：午+晚餐由 assembler 在求解后插入，不在 OR-Tools 的
    # time dimension 内。若用满 DAY_BUDGET 排景点+交通，加餐饮后会超预算(498>480)。
    solve_budget = max(1, DAY_BUDGET - (LUNCH_MIN + DINNER_MIN))
    routes, dropped_idx, relax = solve_vrptw(matrix, nodes, days, solve_budget,
                                             time_windows=tw, ratings=ratings)

    # 就近餐厅池(按每天簇中心)
    food_kw = (state.get("preferences") or {}).get("food") or "美食"
    city_pool = state.get("restaurants", []) or []
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
    day_plans = await annotate_soft_fields(skeleton, state, config)

    dropped_solver = [{"name": candidates[i - 1].get("name", ""),
                       "rating": candidates[i - 1].get("rating", 0.0),
                       "reason": "综合距离/时间/评分权衡后未排入"}
                      for i in dropped_idx if 1 <= i <= len(candidates)]
    return {
        "daily_centers": centers,
        "day_plans": day_plans,
        "dropped_attractions": dropped_pre + dropped_solver,
        "plan_version": (state.get("plan_version", 0) or 0) + 1,
        "changed_days": [d["day"] for d in day_plans],
        "relax_level": relax,
    }
