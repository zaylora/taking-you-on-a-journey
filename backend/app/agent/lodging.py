# -*- coding: utf-8 -*-
"""住宿纯函数与 schema（迁自 accommodation 节点）。过夜日=除最后一天。"""
from pydantic import BaseModel, Field

from app.agent.planning import Hotel

_LEVEL_KEYWORD = {"经济": "经济型酒店", "舒适": "舒适型酒店", "高端": "高档酒店"}

ACCO_SYS = (
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
    """把 assignments（[{day, hotel}]）嵌入对应天，返回新 day_plans。不改原对象。"""
    by_day = {a["day"]: a["hotel"] for a in assignments}
    out = []
    for d in day_plans:
        dd = dict(d)
        if d.get("day") in by_day:
            dd["hotel"] = by_day[d["day"]]
        out.append(dd)
    return out
