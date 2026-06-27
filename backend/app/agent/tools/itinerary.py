# -*- coding: utf-8 -*-
"""Itinerary assembly Agent tool."""
import os
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field, field_validator

from app.agent.itinerary.schemas import DayPlans, ITINERARY_SYS
from app.agent.itinerary.routing.assembler import routes_to_day_plans
from app.agent.itinerary.routing.matrix import duration_matrix
from app.agent.itinerary.routing.optimizer import solve_vrptw
from app.agent.itinerary.routing.prefilter import select_candidates
from app.core.config import get_settings
from app.llm.factory import build_llm

from .utils import parse_jsonish_string


class AssembleItineraryArgs(BaseModel):
    """编排行程工具输入。字段说明会暴露给模型用于生成工具调用参数。"""

    city: str = Field(description="目标城市名称，如 广州。")
    days: int = Field(ge=1, description="规划天数，必须是正整数。")
    attractions: list[dict[str, Any]] = Field(
        description=(
            "景点 POI 数组，优先传 search_attractions 的返回结果原生数组；"
            "每项通常包含 name、poi_id、lng、lat、address、type。不要传字符串。"
        )
    )
    restaurants: list[dict[str, Any]] = Field(
        description=(
            "餐厅 POI 数组，优先传 search_restaurants 的返回结果原生数组；"
            "可为空数组。不要传字符串。"
        )
    )
    weather: dict[str, Any] = Field(
        description="天气对象，优先传 get_weather 的返回结果原生对象；不要传字符串。"
    )
    start_date: str = Field(
        default="",
        description="行程开始日期，格式 YYYY-MM-DD；未知可传空字符串。",
    )
    num_people: int = Field(default=1, ge=1, description="出行人数，必须是正整数。")
    budget_advice: dict[str, Any] | None = Field(
        default=None,
        description=(
            "预算建议对象，来自预算工具返回的 cut_suggestions / over_amount，"
            "用于重新编排行程时压低花费。必须传 JSON 对象或 null；不要传字符串，"
            "不要传 \"None\"，也不要传序列化后的 JSON 字符串。"
        ),
    )

    @field_validator("budget_advice", mode="before")
    @classmethod
    def _coerce_budget_advice(cls, value: Any) -> Any:
        return parse_jsonish_string(value)


def _distance_cache_path() -> str:
    """由 checkpoint 库路径派生同目录下独立的距离缓存库文件名。"""
    ckpt = get_settings().checkpoint_db_path
    d = os.path.dirname(ckpt) or "."
    return os.path.join(d, "distance_cache.sqlite")


@tool(args_schema=AssembleItineraryArgs)
async def assemble_itinerary(city: str, days: int, attractions: list, restaurants: list,
                             weather: dict, start_date: str = "", num_people: int = 1,
                             budget_advice: dict | None = None) -> dict:
    """把景点编排成逐日行程。内部用 OR-Tools VRPTW 求最优分天+顺路（高德真实街道时间），
    再由 LLM 填软字段（时间段/人均cost/说明）。返回 {day_plans, daily_centers}。
    budget_advice 非空时压低花费。候选为空时返回空行程。"""
    candidates = select_candidates(attractions or [], days)
    if not candidates:
        return {"day_plans": [], "daily_centers": []}

    # depot = 候选质心，作为 0 号节点
    cx = sum(c["lng"] for c in candidates) / len(candidates)
    cy = sum(c["lat"] for c in candidates) / len(candidates)
    depot = {"poi_id": "__depot__", "lng": cx, "lat": cy}
    nodes = [depot] + candidates

    matrix = await duration_matrix(nodes, _distance_cache_path())
    routes = solve_vrptw(matrix, days)  # 每天节点索引(指向 nodes，0=depot)
    skeleton = routes_to_day_plans(routes, candidates)  # assembler 用 1-based 指向 candidates

    # 每天活动中心 = 当天景点质心
    daily_centers = []
    for day_plan in skeleton:
        items = day_plan.get("items", [])
        if items:
            dx = sum(it["location"]["lng"] for it in items) / len(items)
            dy = sum(it["location"]["lat"] for it in items) / len(items)
        else:
            dx = dy = 0.0
        daily_centers.append({"lng": dx, "lat": dy})

    # soft_fill：LLM 填时间/cost/note + 就近插餐厅，不改顺序与分天
    payload = {
        "skeleton": skeleton, "restaurants": restaurants or [], "weather": weather or {},
        "start_date": start_date, "num_people": max(1, num_people),
    }
    if budget_advice:
        payload["budget_advice"] = budget_advice
    llm = build_llm(temperature=0).with_structured_output(DayPlans, method="function_calling")
    result = await llm.ainvoke([
        SystemMessage(content=ITINERARY_SYS),
        HumanMessage(content=str(payload)),
    ])
    return {
        "day_plans": [d.model_dump(by_alias=True) for d in result.days],
        "daily_centers": daily_centers,
    }
