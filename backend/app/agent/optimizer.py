# -*- coding: utf-8 -*-
"""OR-Tools VRPTW 求解：days 辆车从 depot(0) 出发覆盖所有候选点，最小化总行驶时间。

分天均衡：每车（每天）访问点数上限 ceil((n-1)/days)，根治某天空着。
无解时放松均衡约束重试。纯函数（OR-Tools 确定性）。
"""
import math

from ortools.constraint_solver import pywrapcp, routing_enums_pb2


def solve_vrptw(duration_matrix: list[list[float]], days: int) -> list[list[int]]:
    n = len(duration_matrix)
    days = max(1, days)
    if n <= 1:
        return [[] for _ in range(days)]

    def _solve(cap: int) -> list[list[int]] | None:
        mgr = pywrapcp.RoutingIndexManager(n, days, 0)  # 0 = depot
        routing = pywrapcp.RoutingModel(mgr)

        def _cost(from_idx, to_idx):
            i, j = mgr.IndexToNode(from_idx), mgr.IndexToNode(to_idx)
            return int(duration_matrix[i][j])

        transit = routing.RegisterTransitCallback(_cost)
        routing.SetArcCostEvaluatorOfAllVehicles(transit)

        # 均衡：每点 demand=1，每车容量 cap
        def _demand(idx):
            return 0 if mgr.IndexToNode(idx) == 0 else 1

        dem = routing.RegisterUnaryTransitCallback(_demand)
        routing.AddDimensionWithVehicleCapacity(dem, 0, [cap] * days, True, "Count")

        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        params.time_limit.FromSeconds(3)
        sol = routing.SolveWithParameters(params)
        if sol is None:
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
        return routes

    base_cap = math.ceil((n - 1) / days)
    for cap in (base_cap, base_cap + 1, n - 1):  # 放松：均衡→宽松→无均衡
        routes = _solve(cap)
        if routes is not None and any(r for r in routes):
            return routes
    # 兜底：顺序均分
    pts = list(range(1, n))
    return [pts[i::days] for i in range(days)]
