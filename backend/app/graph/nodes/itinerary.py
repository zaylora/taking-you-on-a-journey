"""itinerary 节点：cluster_by_day 聚类分天（纯函数） + LLM 填充 day_plans（Task 8）。"""
import math

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.llm.factory import build_llm
from app.tools import amap
from app.graph.nodes.time_budget import DAY_BUDGET, attraction_minutes

# —— 路线规划阈值（M6）——
WALK_KM = 1.0          # <1km 步行
TRANSIT_KM = 5.0       # 1~5km 公交（含地铁）；>5km 驾车
AROUND_RADIUS_M = 3000 # 周边餐厅搜索半径(米)


# ---------------------------------------------------------------------------
# Pydantic schemas for structured LLM output
# ---------------------------------------------------------------------------

class Location(BaseModel):
    lng: float = Field(default=0.0, description="经度，沿用输入坐标，不要自行编造")
    lat: float = Field(default=0.0, description="纬度，沿用输入坐标，不要自行编造")


class DayWeather(BaseModel):
    text: str = Field(default="", description="天气描述，如“晴”“小雨”；沿用输入天气数据")
    temp: str = Field(default="", description="气温，如“18~26℃”；沿用输入天气数据")
    is_rainy: bool = Field(default=False, description="当天是否下雨，下雨时应优先安排室内项")


class PlanItem(BaseModel):
    type: str = Field(
        description="行程项类型，仅限三种：attraction（景点）、meal（餐饮）、transport（交通）"
    )
    name: str = Field(default="", description="景点或餐厅名称；transport 项可留空")
    poi_id: str = Field(default="", description="高德 POI id，沿用输入数据，不要编造")
    location: Location = Field(default_factory=Location, description="该项经纬度，沿用输入坐标")
    start: str = Field(default="", description="开始时间，24 小时制 HH:MM，如 09:30")
    end: str = Field(default="", description="结束时间，24 小时制 HH:MM，如 11:30")
    indoor: bool = Field(default=False, description="是否室内项；雨天优先安排 indoor=true 的项")
    note: str = Field(default="", description="补充说明，一句话简述安排理由或注意事项")
    mode: str = Field(default="", description="交通方式，如“步行”“地铁”“驾车”；仅 transport 项填写")
    from_: str = Field(default="", alias="from", description="交通出发地名称；仅 transport 项填写")
    to: str = Field(default="", description="交通目的地名称；仅 transport 项填写")
    cost: float = Field(default=0.0, description="该项人均花费(元)：门票/餐标/市内交通；免费景点或交通项填 0")

    model_config = {"populate_by_name": True}


class Hotel(BaseModel):
    name: str = Field(default="", description="酒店名称，沿用候选池，不要编造")
    poi_id: str = Field(default="", description="高德 POI id；降级参考酒店可留空")
    location: Location = Field(default_factory=Location, description="酒店经纬度")
    price: float = Field(default=0.0, description="每晚整间价(元)，按住宿档位估")
    level: str = Field(default="", description="住宿档位：经济/舒适/高端")


class DayPlan(BaseModel):
    day: int = Field(description="第几天，从 1 开始的正整数")
    date: str = Field(default="", description="当天日期，格式 YYYY-MM-DD；由 start_date 顺延推算")
    weather: DayWeather = Field(default_factory=DayWeather, description="当天天气，沿用输入天气数据")
    center: Location = Field(default_factory=Location, description="当天活动的中心坐标")
    items: list[PlanItem] = Field(
        default_factory=list,
        description="当天按时间顺序排列的行程项，含景点、餐饮与必要的市内交通",
    )
    hotel: Hotel | None = Field(default=None, description="当晚住宿；离程日/单日游为 None")


class DayPlans(BaseModel):
    days: list[DayPlan] = Field(
        default_factory=list, description="逐天的行程安排列表，长度应等于总天数 days"
    )


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYS = (
    "你是行程编排助手。下面给你的是已经排好顺序、坐标固定的逐日骨架（景点/餐饮/交通段都已确定）。"
    "你的唯一任务：为每个『景点』和『餐饮』项补充 start/end（HH:MM）、cost（人均元）、indoor（是否室内）、note（一句话）。"
    "严禁修改名称、坐标、顺序，严禁增删项，严禁改交通段。雨天优先把户外项标注合理。"
    "若输入含 budget_advice（上轮超支额），据此压低 cost 估计。"
    "按给定结构返回（poi_id/type 原样不动，只补软字段）。"
)


# ---------------------------------------------------------------------------
# Pure helper functions (Task 4 — keep unchanged)
# ---------------------------------------------------------------------------

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
    return {"type": "attraction", "name": p.get("name", ""), "poi_id": p.get("poi_id", ""),
            "location": {"lng": p.get("lng", 0.0), "lat": p.get("lat", 0.0)}}


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
            dropped.append({**p, "reason": "超出总时间预算（按评分取舍）"})
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
                                 "poi_id": it.get("poi_id", "")} for it in d["items"]]}
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
    clusters = cluster_by_day(attractions, days)

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
    }
