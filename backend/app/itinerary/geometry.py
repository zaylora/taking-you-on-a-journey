# -*- coding: utf-8 -*-
"""itinerary 几何纯函数：距离/交通方式/停靠点/交通段。零 I/O，可单测。"""
import math

from app.core.constants import WALK_KM, TRANSIT_KM


def _dist(a: dict, b: dict) -> float:
    return math.hypot(a.get("lng", 0.0) - b.get("lng", 0.0),
                      a.get("lat", 0.0) - b.get("lat", 0.0))


def haversine_km(a: dict, b: dict) -> float:
    """两点直线距离(km)。手写标准公式（依赖优先原则：单一公式不引依赖）。"""
    R = 6371.0
    lat1, lat2 = math.radians(a.get("lat", 0.0)), math.radians(b.get("lat", 0.0))
    dlat = lat2 - lat1
    dlng = math.radians(b.get("lng", 0.0) - a.get("lng", 0.0))
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def mode_by_distance(km: float) -> str:
    """按直线距离定交通方式。返回值必须与前端选插件关键字一致。"""
    if km < WALK_KM:
        return "步行"
    if km < TRANSIT_KM:
        return "公交"
    return "驾车"


def pick_nearest(pool: list[dict], anchor: dict, used: set[str]) -> dict | None:
    """从 pool 里挑离 anchor 最近、poi_id 未用过的一项；无则 None。"""
    cands = [p for p in pool if p.get("poi_id") and p["poi_id"] not in used]
    if not cands:
        return None
    return min(cands, key=lambda p: haversine_km(p, anchor))


def _attraction_item(p: dict) -> dict:
    item = {"type": "attraction", "name": p.get("name", ""), "poi_id": p.get("poi_id", ""),
            "location": {"lng": p.get("lng", 0.0), "lat": p.get("lat", 0.0)}}
    # 透传 enrich 估出的游玩时长，使 day_plans 落地后 refine/budget 重算口径一致
    vm = p.get("visit_minutes")
    if isinstance(vm, (int, float)) and vm > 0:
        item["visit_minutes"] = int(vm)
    # 透传营业时间，供 LLM 软填 start/end 时参考（晚到/早闭），并可下发前端展示
    if p.get("opentime"):
        item["opentime"] = p["opentime"]
    return item


def _meal_item(p: dict) -> dict:
    return {"type": "meal", "name": p.get("name", ""), "poi_id": p.get("poi_id", ""),
            "location": {"lng": p.get("lng", 0.0), "lat": p.get("lat", 0.0)}}


def build_day_stops(attractions_ordered: list[dict], rest_pool: list[dict]) -> list[dict]:
    """顺路停靠点：景点顺序不变，过半插就近午餐、末尾插就近晚餐（poi 去重）。"""
    stops: list[dict] = []
    n = len(attractions_ordered)
    if n == 0:
        return stops
    used: set[str] = set()
    lunch_after = (n + 1) // 2
    for i, a in enumerate(attractions_ordered, start=1):
        stops.append(_attraction_item(a))
        if n >= 2 and i == lunch_after:
            r = pick_nearest(rest_pool, {"lng": a.get("lng", 0.0), "lat": a.get("lat", 0.0)}, used)
            if r:
                used.add(r["poi_id"])
                stops.append(_meal_item(r))
    last = attractions_ordered[-1]
    dinner = pick_nearest(rest_pool, {"lng": last.get("lng", 0.0), "lat": last.get("lat", 0.0)}, used)
    if dinner:
        used.add(dinner["poi_id"])
        stops.append(_meal_item(dinner))
    return stops


def default_cost_by_mode(mode: str, km: float) -> float:
    """交通段人均粗估(元)：步行 0 / 公交 3 / 驾车 起步+里程。不进 LLM，保证 budget 汇总稳定。"""
    if mode == "步行":
        return 0.0
    if mode == "公交":
        return 3.0
    return round(2.0 + 2.0 * km, 1)


def _transport_item(p: dict, q: dict) -> dict:
    lp, lq = p["location"], q["location"]
    km = haversine_km(lp, lq)
    mode = mode_by_distance(km)
    return {"type": "transport", "name": "",
            "from": p.get("name", ""), "to": q.get("name", ""),
            "location": {"lng": lp["lng"], "lat": lp["lat"]},
            "mode": mode, "cost": default_cost_by_mode(mode, km)}


def insert_transport(stops: list[dict]) -> list[dict]:
    """在每对相邻停靠点间插一个交通段（起讫坐标沿用相邻点，mode 按直线距离）。"""
    if len(stops) < 2:
        return list(stops)
    out = [stops[0]]
    for prev, cur in zip(stops, stops[1:]):
        out.append(_transport_item(prev, cur))
        out.append(cur)
    return out
