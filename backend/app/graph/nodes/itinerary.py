"""itinerary 节点：cluster_by_day 聚类分天（纯函数） + LLM 填充 day_plans（Task 8）。"""
import math


def _dist(a: dict, b: dict) -> float:
    return math.hypot(a.get("lng", 0.0) - b.get("lng", 0.0),
                      a.get("lat", 0.0) - b.get("lat", 0.0))


def cluster_by_day(points: list[dict], days: int) -> list[list[dict]]:
    """手写贪心：按到城市中心的方位角排序 → 均衡切 days 段 → 段内最近邻顺路。
    纯函数、零依赖。接口固定，未来可替换为 KMeans 而不动调用方。
    """
    days = max(1, days)
    buckets: list[list[dict]] = [[] for _ in range(days)]
    if not points:
        return buckets

    # 城市中心 = 质心
    cx = sum(p.get("lng", 0.0) for p in points) / len(points)
    cy = sum(p.get("lat", 0.0) for p in points) / len(points)
    center = {"lng": cx, "lat": cy}

    # 按方位角排序，使同方向的点相邻，便于「顺路」分天
    ordered = sorted(points, key=lambda p: math.atan2(p.get("lat", 0.0) - cy,
                                                       p.get("lng", 0.0) - cx))

    # 均衡切片：前 (n % days) 段各多 1 个
    n = len(ordered)
    base, extra = divmod(n, days)
    idx = 0
    for d in range(days):
        size = base + (1 if d < extra else 0)
        seg = ordered[idx:idx + size]
        idx += size
        buckets[d] = _nearest_neighbor_order(seg, center)
    return buckets


def _nearest_neighbor_order(seg: list[dict], center: dict) -> list[dict]:
    if not seg:
        return []
    remaining = list(seg)
    # 起点：离中心最近的点
    cur = min(remaining, key=lambda p: _dist(p, center))
    remaining.remove(cur)
    route = [cur]
    while remaining:
        nxt = min(remaining, key=lambda p: _dist(p, route[-1]))
        remaining.remove(nxt)
        route.append(nxt)
    return route


async def itinerary(state, config):
    return {}  # TODO(Task 8): 聚类 + LLM 填充 day_plans
