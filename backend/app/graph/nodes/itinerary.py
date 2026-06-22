"""itinerary 节点：cluster_by_day 聚类分天（纯函数） + LLM 填充 day_plans（Task 8）。"""
import math

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm.factory import build_llm
from app.tools import amap
from app.graph.nodes.time_budget import (
    DAY_BUDGET, LUNCH_MIN, DINNER_MIN, attraction_minutes, transit_minutes,
)
from app.core.constants import AROUND_RADIUS_M

# —— re-export：下游 refine/accommodation/answer/tests 依赖这些符号的旧路径 ——
from app.itinerary.geometry import (  # noqa: F401
    haversine_km, mode_by_distance, pick_nearest, build_day_stops,
    default_cost_by_mode, insert_transport,
    _dist,  # noqa: F401
)
from app.itinerary.schemas import (  # noqa: F401
    Location, DayWeather, PlanItem, Hotel, DayPlan, DayPlans,
)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYS = (
    "你是行程编排助手。下面给你的是已经排好顺序、坐标固定的逐日骨架（景点/餐饮/交通段都已确定）。"
    "你的唯一任务：为每个『景点』和『餐饮』项补充 start/end（HH:MM）、cost（人均元）、indoor（是否室内）、note（一句话）。"
    "严禁修改名称、坐标、顺序，严禁增删项，严禁改交通段。雨天优先把户外项标注合理。"
    "若项含 opentime（营业时间），设置 start/end 时务必落在营业时间内（避免早到未开/晚到已闭）。"
    "若输入含 budget_advice（上轮超支额），据此压低 cost 估计。"
    "按给定结构返回（poi_id/type 原样不动，只补软字段）。"
)


_SOFT_FIELDS = ("start", "end", "cost", "indoor", "note")


def merge_soft_fields(skeleton_days: list[dict], llm_days: list[dict]) -> list[dict]:
    """把 LLM 的软字段合并进算法骨架：按 day + poi_id 对齐非交通项，仅覆盖非空软字段；
    顺序、坐标、交通段一律以骨架为准。纯函数，不改输入。"""
    llm_by_day = {d.get("day"): d for d in llm_days}
    out = []
    for sd in skeleton_days:
        ld = llm_by_day.get(sd.get("day"), {}) or {}
        soft_by_poi = {it.get("poi_id"): it for it in ld.get("items", [])
                       if it.get("type") != "transport" and it.get("poi_id")}
        new_items = []
        for it in sd.get("items", []):
            merged = dict(it)
            if it.get("type") != "transport":
                src = soft_by_poi.get(it.get("poi_id"))
                if src:
                    for k in _SOFT_FIELDS:
                        v = src.get(k)
                        if v not in (None, ""):
                            merged[k] = v
            new_items.append(merged)
        nd = dict(sd)
        nd["items"] = new_items
        out.append(nd)
    return out


OVERHEAD_PER_STOP = 40  # 每景点分摊的餐饮/交通/缓冲开销(分钟)


def select_by_rating(attractions: list[dict], days: int,
                     day_budget: int = DAY_BUDGET) -> tuple[list[dict], list[dict]]:
    """按评分降序装到总时间预算，宁缺勿滥。返回 (selected, dropped)。
    评分相同按 poi_id 字典序保证确定性。dropped 每项带 reason。
    """
    total_budget = max(1, days) * day_budget
    ranked = sorted(attractions,
                    key=lambda p: (-p.get("rating", 0.0), p.get("poi_id", "")))
    selected, dropped = [], []
    used = 0
    for p in ranked:
        cost = attraction_minutes(p) + OVERHEAD_PER_STOP
        if used + cost <= total_budget:
            selected.append(p)
            used += cost
        else:
            dropped.append({"name": p.get("name", ""), "rating": p.get("rating", 0.0),
                            "reason": "超出总时间预算（按评分取舍）"})
    return selected, dropped


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
        buckets[d] = _nearest_neighbor_order(seg)
    return buckets


def cluster_kmeans(points: list[dict], days: int) -> list[list[dict]]:
    """按经纬度 KMeans 聚成 days 群，每群内部最近邻排序。
    目标：同一天的景点地理紧凑。点数<days 或 sklearn 不可用时回退 cluster_by_day。
    """
    days = max(1, days)
    if not points:
        return [[] for _ in range(days)]
    if len(points) < days:
        return cluster_by_day(points, days)
    try:
        from sklearn.cluster import KMeans
    except ImportError:
        return cluster_by_day(points, days)

    # 纬度等距投影：经度按 cos(lat) 缩放，避免高纬度经度被高估
    lat0 = sum(p.get("lat", 0.0) for p in points) / len(points)
    scale = math.cos(math.radians(lat0)) or 1.0
    feats = [[p.get("lng", 0.0) * scale, p.get("lat", 0.0)] for p in points]
    labels = KMeans(n_clusters=days, random_state=42, n_init=10).fit_predict(feats)

    buckets: list[list[dict]] = [[] for _ in range(days)]
    for p, lbl in zip(points, labels):
        buckets[int(lbl)].append(p)
    return [_nearest_neighbor_order(b) for b in buckets]


def _bucket_load(bucket: list[dict]) -> int:
    """桶内当天用时估计，与 day_used_minutes 同口径：
    景点停留 + 餐饮占用（≥2 景点配午+晚=120，1 景点配晚餐 60）+ 最近邻顺序的景点间交通。
    交通用 mode_by_distance 选方式、transit_minutes 估时，保证 rebalance 的预算闸门
    与下游真实 day_used_minutes 一致（避免分散日实际超预算）。
    """
    if not bucket:
        return 0
    total = sum(attraction_minutes(a) for a in bucket)
    total += LUNCH_MIN + DINNER_MIN if len(bucket) >= 2 else DINNER_MIN
    ordered = _nearest_neighbor_order(bucket)
    for a, b in zip(ordered, ordered[1:]):
        km = haversine_km({"lng": a.get("lng", 0.0), "lat": a.get("lat", 0.0)},
                          {"lng": b.get("lng", 0.0), "lat": b.get("lat", 0.0)})
        total += transit_minutes(km, mode_by_distance(km))
    return total


def _bucket_center(bucket: list[dict]) -> dict:
    if not bucket:
        return {"lng": 0.0, "lat": 0.0}
    return {"lng": sum(a.get("lng", 0.0) for a in bucket) / len(bucket),
            "lat": sum(a.get("lat", 0.0) for a in bucket) / len(bucket)}


def rebalance_by_budget(buckets: list[list[dict]],
                        day_budget: int = DAY_BUDGET) -> tuple[list[list[dict]], list[dict]]:
    """超预算的天弹出最低分景点 → 塞入地理最近且有余量的天；无处可塞则丢弃。
    返回 (balanced_buckets, dropped)。确定性：迁移目标按 (距离, 桶序) 排序。
    """
    buckets = [list(b) for b in buckets]
    dropped: list[dict] = []
    for i, bucket in enumerate(buckets):
        # 反复弹出最低分，直到该桶不超预算
        while _bucket_load(bucket) > day_budget and bucket:
            victim = min(bucket, key=lambda a: (a.get("rating", 0.0), a.get("poi_id", "")))
            bucket.remove(victim)
            need = attraction_minutes(victim) + OVERHEAD_PER_STOP
            # 候选目标天：有余量者，按到该天中心的距离升序
            targets = sorted(
                (j for j in range(len(buckets))
                 if j != i and _bucket_load(buckets[j]) + need <= day_budget),
                key=lambda j: (haversine_km(victim, _bucket_center(buckets[j])), j),
            )
            if targets:
                buckets[targets[0]].append(victim)
            else:
                dropped.append({"name": victim.get("name", ""), "rating": victim.get("rating", 0.0),
                                "reason": "各天时间预算已满，无法安排"})
        buckets[i] = bucket
    # 迁移后各桶内部重新最近邻排序
    return [_nearest_neighbor_order(b) for b in buckets], dropped


def _nearest_neighbor_order(seg: list[dict]) -> list[dict]:
    if not seg:
        return []
    remaining = list(seg)
    # 起点：经纬度字典序最小的「端点」（确定性；共线时保证单调顺路，不从中间起步）
    cur = min(remaining, key=lambda p: (p.get("lng", 0.0), p.get("lat", 0.0)))
    remaining.remove(cur)
    route = [cur]
    while remaining:
        nxt = min(remaining, key=lambda p: _dist(p, route[-1]))
        remaining.remove(nxt)
        route.append(nxt)
    return route


# ---------------------------------------------------------------------------
# Async graph node (Task 8)
# ---------------------------------------------------------------------------

def _build_payload(skeleton_days: list, state: dict) -> dict:
    """构造软填 LLM 的输入：骨架（仅供补软字段）+ 天气 + 可选 budget_advice。纯函数，便于单测。"""
    payload = {
        "skeleton": [{"day": d["day"],
                      "items": [{"type": it["type"], "name": it.get("name", ""),
                                 "poi_id": it.get("poi_id", ""),
                                 **({"opentime": it["opentime"]} if it.get("opentime") else {})}
                                for it in d["items"]]}
                     for d in skeleton_days],
        "weather": state.get("weather", {}),
        "num_people": state.get("num_people", 1) or 1,
    }
    advice = state.get("budget_advice")
    if advice:
        payload["budget_advice"] = advice
    return payload


async def itinerary(state, config) -> dict:
    days = state.get("days", 3) or 3
    attractions = state.get("attractions", []) or []
    selected, dropped = select_by_rating(attractions, days)
    clusters = cluster_kmeans(selected, days)
    clusters, dropped_balance = rebalance_by_budget(clusters)
    dropped = dropped + dropped_balance

    daily_centers = []
    for c in clusters:
        if c:
            cx = sum(p.get("lng", 0.0) for p in c) / len(c)
            cy = sum(p.get("lat", 0.0) for p in c) / len(c)
        else:
            cx = cy = 0.0
        daily_centers.append({"lng": cx, "lat": cy})

    food_kw = (state.get("preferences") or {}).get("food") or "美食"
    city_pool = state.get("restaurants", []) or []  # 周边搜索为空时兜底

    skeleton_days = []
    for d, (cluster, center) in enumerate(zip(clusters, daily_centers), start=1):
        pool = []
        if center["lng"] or center["lat"]:
            pool = await amap.search_around(center["lng"], center["lat"],
                                            food_kw, "餐饮", AROUND_RADIUS_M)
        if not pool:
            pool = city_pool
        stops = build_day_stops(cluster, pool)
        items = insert_transport(stops)
        skeleton_days.append({"day": d, "items": items, "center": center})

    # LLM 仅填软字段；失败则全用骨架默认
    llm = build_llm(temperature=0).with_structured_output(DayPlans, method="function_calling")
    try:
        result = await llm.ainvoke([
            SystemMessage(content=_SYS),
            HumanMessage(content=str(_build_payload(skeleton_days, state))),
        ], config=config)
        llm_days = [d.model_dump(by_alias=True) for d in result.days]
    except Exception:  # noqa: BLE001 —— 软填失败不阻断，几何已就绪
        llm_days = []

    merged = merge_soft_fields(skeleton_days, llm_days)
    return {
        "daily_centers": daily_centers,
        "day_plans": merged,
        "plan_version": (state.get("plan_version", 0) or 0) + 1,
        "changed_days": [d["day"] for d in merged],
        "dropped_attractions": dropped,
    }
