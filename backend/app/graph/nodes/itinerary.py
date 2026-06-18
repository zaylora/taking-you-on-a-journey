"""itinerary 节点：cluster_by_day 聚类分天（纯函数） + LLM 填充 day_plans（Task 8）。"""
import math

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.llm.factory import build_llm


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
    "你是行程编排助手。给定每天的景点簇、餐厅候选、交通与天气，为每天安排合理的时间线："
    "上午/下午景点、午餐/晚餐就近分配餐厅、必要的市内交通。雨天优先室内项。"
    "为每个行程项估算人均花费 cost（元）：门票按景点合理价、餐标按餐厅档位、市内交通按方式估；"
    "免费景点或无费用项填 0。"
    "若输入含 budget_advice（上轮超支额与削减建议），据此压低总花费："
    "优先减少或替换高价付费景点、降低餐标、精简交通。"
    "输出严格符合给定结构（含每项的 location 经纬度与 cost，沿用输入坐标）。"
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

def _build_payload(state: dict, clusters: list) -> dict:
    """构造传给 LLM 的输入 payload；回退时带上 budget_advice。纯函数，便于单测。"""
    payload = {
        "days": state.get("days", 3) or 3,
        "clusters": clusters,
        "restaurants": state.get("restaurants", []),
        "transport": state.get("transport", {}),
        "weather": state.get("weather", {}),
        "start_date": state.get("start_date", ""),
        "num_people": state.get("num_people", 1) or 1,
    }
    advice = state.get("budget_advice")
    if advice:
        payload["budget_advice"] = advice
    return payload


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
    payload = _build_payload(state, clusters)
    result = await llm.ainvoke([
        SystemMessage(content=_SYS),
        HumanMessage(content=str(payload)),
    ], config=config)
    return {
        "daily_centers": daily_centers,
        "day_plans": [d.model_dump(by_alias=True) for d in result.days],
    }
