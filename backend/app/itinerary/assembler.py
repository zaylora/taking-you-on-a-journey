# -*- coding: utf-8 -*-
"""求解结果(每天节点序列) -> skeleton_days:插就近餐厅 + 交通段。几何不变量在此守住。"""
from app.itinerary.geometry import build_day_stops, insert_transport


def _center(points: list[dict]) -> dict:
    if not points:
        return {"lng": 0.0, "lat": 0.0}
    return {"lng": sum(p.get("lng", 0.0) for p in points) / len(points),
            "lat": sum(p.get("lat", 0.0) for p in points) / len(points)}


def routes_to_skeleton(per_day_routes: list[list[int]], candidates: list[dict],
                       rest_pools: list[list[dict]]) -> tuple[list[dict], list[dict]]:
    """per_day_routes[d] 是节点 index 列表(基于 [depot]+candidates,故 index i->candidates[i-1])。
    每天:取有序景点 -> build_day_stops(插就近餐厅) -> insert_transport(插交通段)。
    """
    skeleton, centers = [], []
    for d, route in enumerate(per_day_routes, start=1):
        ordered = [candidates[i - 1] for i in route if 1 <= i <= len(candidates)]
        pool = rest_pools[d - 1] if d - 1 < len(rest_pools) else []
        stops = build_day_stops(ordered, pool)
        items = insert_transport(stops)
        center = _center(ordered)
        skeleton.append({"day": d, "items": items, "center": center})
        centers.append(center)
    return skeleton, centers
