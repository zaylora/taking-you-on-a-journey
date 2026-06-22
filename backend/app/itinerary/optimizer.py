# -*- coding: utf-8 -*-
"""OR-Tools VRPTW：选点+分天+顺路+时间窗联合求解，含三级放松约束重解。

天=车辆、景点=节点、visit_minutes=service time、time_window=营业时间、
rating=丢弃惩罚。无可行解时按 L1(去窗)->L2(放宽预算)->L3(去时间维度) 逐级放松。

均衡分天：加一个计数维度 Count（每访问一个景点 +1），对每辆车设硬上限
ceil(可选点数/天数)，把景点摊到每一天，避免求解器为省路程把所有点塞进一天、
其余天空着。该上限与 disjunction 不冲突（丢点只会让某车更少，不会导致无解），
且在去时间维度的 L3 放松层仍保留（它不是时间约束）。
"""
import math

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.core.constants import SOLVE_TIME_LIMIT_S, RELAX_BUDGET_FACTOR


def _solve_once(matrix, nodes, days, day_budget, time_windows, ratings, use_time_dim):
    n = len(matrix)
    mgr = pywrapcp.RoutingIndexManager(n, days, 0)
    routing = pywrapcp.RoutingModel(mgr)

    def transit_cb(i, j):
        fi, fj = mgr.IndexToNode(i), mgr.IndexToNode(j)
        service = int(nodes[fj].get("visit_minutes", 0))
        return int(matrix[fi][fj]) + service

    cb = routing.RegisterTransitCallback(transit_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(cb)

    # 计数维度：每车（每天）访问景点数上限 = ceil(可选点数 / 天数)，均衡摊开
    def count_cb(i):
        return 0 if mgr.IndexToNode(i) == 0 else 1

    ccb = routing.RegisterUnaryTransitCallback(count_cb)
    per_day_max = max(1, math.ceil((n - 1) / days)) if n > 1 else 0
    routing.AddDimensionWithVehicleCapacity(
        ccb, 0, [per_day_max] * days, True, "Count")

    if use_time_dim:
        routing.AddDimension(cb, 0, int(day_budget), True, "Time")
        time_dim = routing.GetDimensionOrDie("Time")
        if time_windows:
            for node in range(1, n):
                a, b = time_windows[node]
                idx = mgr.NodeToIndex(node)
                time_dim.CumulVar(idx).SetRange(int(a), int(b))

    # disjunction：高分高惩罚
    for node in range(1, n):
        rating = ratings[node] if ratings else 3.0
        penalty = int(rating * 1000) + 500
        routing.AddDisjunction([mgr.NodeToIndex(node)], penalty)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromSeconds(int(SOLVE_TIME_LIMIT_S))

    sol = routing.SolveWithParameters(params)
    if not sol:
        return None
    routes = []
    for v in range(days):
        idx = routing.Start(v)
        route = []
        while not routing.IsEnd(idx):
            node = mgr.IndexToNode(idx)
            if node != 0:
                route.append(node)
            idx = sol.Value(routing.NextVar(idx))
        routes.append(route)
    visited = {x for r in routes for x in r}
    dropped = [node for node in range(1, n) if node not in visited]
    return routes, dropped


def solve_vrptw(matrix, nodes, days, day_budget, time_windows=None, ratings=None):
    """逐级放松：L0 原约束 -> L1 去时间窗 -> L2 放宽预算 -> L3 去时间维度。
    返回 (per_day_routes, dropped_node_indices, relax_level)。
    """
    days = max(1, days)
    # L0
    r = _solve_once(matrix, nodes, days, day_budget, time_windows, ratings, True)
    if r is not None and any(route for route in r[0]):
        return r[0], r[1], 0
    # L1：去时间窗
    r = _solve_once(matrix, nodes, days, day_budget, None, ratings, True)
    if r is not None and any(route for route in r[0]):
        return r[0], r[1], 1
    # L2：放宽预算
    r = _solve_once(matrix, nodes, days, int(day_budget * RELAX_BUDGET_FACTOR),
                    None, ratings, True)
    if r is not None and any(route for route in r[0]):
        return r[0], r[1], 2
    # L3：去时间维度（纯路由）
    r = _solve_once(matrix, nodes, days, day_budget, None, ratings, False)
    if r is not None:
        return r[0], r[1], 3
    # 兜底：全丢弃（理论不达）
    return [[] for _ in range(days)], list(range(1, len(matrix))), 3
