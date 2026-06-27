# -*- coding: utf-8 -*-
"""路线索引 → DayPlan 骨架（仅景点项，软字段留空待 soft_fill 填）。纯函数。"""


def routes_to_day_plans(routes: list[list[int]], candidates: list[dict]) -> list[dict]:
    """routes[d] 是第 d 天的节点索引列表（1-based 指向 candidates；depot(0) 若存在会被跳过）。"""
    plans = []
    for d, route in enumerate(routes, start=1):
        items = []
        for node_idx in route:
            if node_idx == 0:  # 跳过 depot
                continue
            c = candidates[node_idx - 1]  # node 1 → candidates[0]
            items.append({
                "type": "attraction", "name": c.get("name", ""),
                "poi_id": c.get("poi_id", ""),
                "location": {"lng": c.get("lng", 0.0), "lat": c.get("lat", 0.0)},
                "start": "", "end": "", "indoor": False, "note": "", "cost": 0.0,
            })
        plans.append({"day": d, "items": items})
    return plans
