"""accommodation 节点（M4）：高德 POI 检索酒店候选 + LLM 按档位/就近分配到每个过夜日，嵌回 day_plans。

过夜日 = 除最后一天外的每天（离程日不住）；单日游无住宿。
POI 检索失败/空 → LLM 仅按档位 + 每日中心坐标生成「参考酒店」，不阻断。
"""
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.graph.nodes.itinerary import Hotel, Location
from app.llm.factory import build_llm
from app.tools import amap

_LEVEL_KEYWORD = {"经济": "经济型酒店", "舒适": "舒适型酒店", "高端": "高档酒店"}

_SYS = (
    "你是住宿规划助手。给定每个过夜日的活动中心坐标、住宿档位与酒店候选池，"
    "为每个过夜日就近选一家酒店，并按档位估每晚整间价 price（元）："
    "经济约 200~400、舒适约 400~800、高端约 800 以上。"
    "优先使用候选池中的真实酒店（带 poi_id 与坐标）；候选池为空时按档位与中心坐标给出参考酒店（poi_id 留空）。"
    "只为给定的过夜日分配，输出严格符合结构。"
)


class _HotelForDay(BaseModel):
    day: int = Field(description="过夜日序号（从 1 开始）")
    hotel: Hotel = Field(description="该晚住宿")


class _AccoResult(BaseModel):
    assignments: list[_HotelForDay] = Field(default_factory=list, description="逐过夜日的住宿分配")


def overnight_days(day_plans: list) -> list:
    """需住宿的天（除最后一天）。纯函数。"""
    days = sorted(d.get("day", 0) for d in day_plans)
    return days[:-1]


def hotel_keyword(level: str) -> str:
    return _LEVEL_KEYWORD.get(level, "酒店")


def attach_hotels(day_plans: list, assignments: list) -> list:
    """把 assignments（[{day, hotel}]）的 hotel 嵌入对应天，返回新 day_plans。纯函数、不改原对象。"""
    by_day = {a["day"]: a["hotel"] for a in assignments}
    out = []
    for d in day_plans:
        dd = dict(d)
        if d.get("day") in by_day:
            dd["hotel"] = by_day[d["day"]]
        out.append(dd)
    return out


async def assign_hotels(day_plans: list, city: str, preferences: dict,
                        daily_centers: list, config=None) -> list:
    """检索酒店 + LLM 按档位/就近分配，嵌回 day_plans。无过夜日返回原 day_plans。纯能力函数。"""
    nights = overnight_days(day_plans)
    if not nights:
        return day_plans
    prefs = preferences or {}
    level = prefs.get("住宿") or prefs.get("accommodation") or "舒适"
    try:
        pool = await amap.search_poi(city, hotel_keyword(level), "住宿服务") if city else []
    except Exception:  # noqa: BLE001 —— 降级，仍交 LLM 生成参考酒店
        pool = []
    llm = build_llm(temperature=0).with_structured_output(_AccoResult, method="function_calling")
    payload = {"overnight_days": nights, "level": level,
               "daily_centers": daily_centers or [], "hotel_pool": pool}
    result = await llm.ainvoke([
        SystemMessage(content=_SYS),
        HumanMessage(content=str(payload)),
    ], config=config)
    assignments = [{"day": a.day, "hotel": a.hotel.model_dump(by_alias=True)}
                   for a in result.assignments]
    return attach_hotels(day_plans, assignments)


async def accommodation(state, config) -> dict:
    """薄壳节点：从 state 取参数调 assign_hotels，行为与原来完全一致。"""
    day_plans = state.get("day_plans", []) or []
    if not overnight_days(day_plans):
        return {}  # 单日游或无行程 → 无住宿
    updated = await assign_hotels(
        day_plans,
        state.get("city", ""),
        state.get("preferences", {}) or {},
        state.get("daily_centers", []) or [],
        config,
    )
    return {"day_plans": updated}
