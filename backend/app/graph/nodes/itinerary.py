"""itinerary 节点：cluster_by_day 聚类分天（纯函数） + LLM 填充 day_plans（Task 8）。"""
import math

from pydantic import BaseModel, Field

from app.llm.factory import build_llm


# ---------------------------------------------------------------------------
# Pydantic schemas for structured LLM output
# ---------------------------------------------------------------------------

class Location(BaseModel):
    lng: float = 0.0
    lat: float = 0.0


class DayWeather(BaseModel):
    text: str = ""
    temp: str = ""
    is_rainy: bool = False


class PlanItem(BaseModel):
    type: str                       # attraction | meal | transport
    name: str = ""
    poi_id: str = ""
    location: Location = Field(default_factory=Location)
    start: str = ""
    end: str = ""
    indoor: bool = False
    note: str = ""
    mode: str = ""                  # transport 用
    from_: str = Field(default="", alias="from")
    to: str = ""

    model_config = {"populate_by_name": True}


class DayPlan(BaseModel):
    day: int
    date: str = ""
    weather: DayWeather = Field(default_factory=DayWeather)
    center: Location = Field(default_factory=Location)
    items: list[PlanItem] = Field(default_factory=list)


class DayPlans(BaseModel):
    days: list[DayPlan] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYS = (
    "你是行程编排助手。给定每天的景点簇、餐厅候选、交通与天气，为每天安排合理的时间线："
    "上午/下午景点、午餐/晚餐就近分配餐厅、必要的市内交通。雨天优先室内项。"
    "输出严格符合给定结构（含每项的 location 经纬度，沿用输入坐标）。"
)


# ---------------------------------------------------------------------------
# Pure helper functions (Task 4 — keep unchanged)
# ---------------------------------------------------------------------------

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

async def itinerary(state, config) -> dict:
    days = state.get("days", 3) or 3
    clusters = cluster_by_day(state.get("attractions", []) or [], days)
    daily_centers = []
    for c in clusters:
        if c:
            cx = sum(p.get("lng", 0.0) for p in c) / len(c)
            cy = sum(p.get("lat", 0.0) for p in c) / len(c)
        else:
            cx = cy = 0.0
        daily_centers.append({"lng": cx, "lat": cy})

    llm = build_llm(temperature=0).with_structured_output(DayPlans, method="function_calling")
    payload = {
        "days": days,
        "clusters": clusters,
        "restaurants": state.get("restaurants", []),
        "transport": state.get("transport", {}),
        "weather": state.get("weather", {}),
        "start_date": state.get("start_date", ""),
    }
    result = await llm.ainvoke([
        {"role": "system", "content": _SYS},
        {"role": "user", "content": str(payload)},
    ], config=config)
    return {
        "daily_centers": daily_centers,
        "day_plans": [d.model_dump(by_alias=True) for d in result.days],
    }
