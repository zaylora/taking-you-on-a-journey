# -*- coding: utf-8 -*-
"""ReAct Agent 工具箱。每个 tool = LLM 可调接口 + 内部确定性实现。

检索类直接复用 app/tools/amap.py（失败降级，不抛）。
编排/核算/收尾类见后续步骤。
"""
import json
import os
import ast
from typing import Annotated, Any

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, Field, field_validator

from app.tools import amap
from app.agent.budgeting import compute_budget
from app.agent.diffing import diff_changed_days
from app.core.config import get_settings
from app.agent.prefilter import select_candidates
from app.agent.matrix import duration_matrix
from app.agent.optimizer import solve_vrptw
from app.agent.assembler import routes_to_day_plans
from app.agent.planning import DayPlans, ITINERARY_SYS
from app.agent.lodging import (
    overnight_days, attach_hotels, hotel_keyword, _AccoResult, ACCO_SYS,
)
from app.llm.factory import build_llm


def _parse_jsonish_string(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return ast.literal_eval(text)


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
        return _parse_jsonish_string(value)


class AssignHotelsArgs(BaseModel):
    """住宿分配工具输入。字段说明会暴露给模型用于生成工具调用参数。"""

    city: str = Field(description="住宿所在城市名称，如 广州。")
    day_plans: list[dict[str, Any]] = Field(
        description=(
            "逐日行程数组，传 assemble_itinerary 或已有最终行程里的 day_plans 原生数组；"
            "不要传字符串。"
        )
    )
    level: str = Field(
        default="舒适",
        description="住宿档位：经济、舒适或高端；用户未指定时默认舒适。",
    )
    daily_centers: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "每天活动中心坐标数组，来自 assemble_itinerary 返回的 daily_centers 原样传入；"
            "每项通常包含 lng、lat。必须传 JSON 数组或 null；不要传字符串，"
            "不要传序列化后的 JSON 字符串。"
        ),
    )

    @field_validator("daily_centers", mode="before")
    @classmethod
    def _coerce_daily_centers(cls, value: Any) -> Any:
        return _parse_jsonish_string(value)


def _distance_cache_path() -> str:
    """由 checkpoint 库路径派生同目录下独立的距离缓存库文件名。"""
    ckpt = get_settings().checkpoint_db_path
    d = os.path.dirname(ckpt) or "."
    return os.path.join(d, "distance_cache.sqlite")


@tool
async def search_attractions(city: str, keywords: str = "热门景点") -> list:
    """检索城市景点 POI。返回 [{name,poi_id,lng,lat,address,type}]；失败或无结果返回 []。"""
    try:
        return await amap.search_poi(city, keywords, "风景名胜")
    except Exception:  # noqa: BLE001 -- 降级，交 LLM 决策
        return []


@tool
async def search_restaurants(city: str, keywords: str = "美食") -> list:
    """检索城市餐饮 POI。返回 [{name,poi_id,lng,lat,...}]；失败或无结果返回 []。"""
    try:
        return await amap.search_poi(city, keywords, "餐饮")
    except Exception:  # noqa: BLE001
        return []


@tool
async def get_weather(city: str) -> dict:
    """查询城市天气。返回 {text,temp,is_rainy,source}；失败降级季节气候。"""
    try:
        return await amap.get_weather(city)
    except Exception:  # noqa: BLE001
        return {"text": "以当季气候为准", "temp": "", "is_rainy": False, "source": "climate"}


@tool
async def plan_route(origin: str, dest: str, mode: str = "transit") -> dict:
    """规划两地交通方案。返回高德 route dict；失败降级 {}。"""
    try:
        return await amap.plan_route(origin, dest, mode)
    except Exception:  # noqa: BLE001
        return {}


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


@tool(args_schema=AssignHotelsArgs)
async def assign_hotels(city: str, day_plans: list, level: str = "舒适",
                        daily_centers: list | None = None) -> list:
    """为过夜日就近分配酒店并嵌入 day_plans。返回更新后的 day_plans；单日游/无行程原样返回。"""
    nights = overnight_days(day_plans)
    if not nights:
        return day_plans
    try:
        pool = await amap.search_poi(city, hotel_keyword(level), "住宿服务") if city else []
    except Exception:  # noqa: BLE001
        pool = []
    payload = {"overnight_days": nights, "level": level,
               "daily_centers": daily_centers or [], "hotel_pool": pool}
    llm = build_llm(temperature=0).with_structured_output(_AccoResult, method="function_calling")
    result = await llm.ainvoke([
        SystemMessage(content=ACCO_SYS),
        HumanMessage(content=str(payload)),
    ])
    assignments = [{"day": a.day, "hotel": a.hotel.model_dump(by_alias=True)}
                   for a in result.assignments]
    return attach_hotels(day_plans, assignments)


@tool
async def compute_budget_tool(day_plans: list, num_people: int = 1, limit: float = 0.0,
                              tool_call_id: Annotated[str, InjectedToolCallId] = "",
                              state: Annotated[dict, InjectedState] = None) -> Command:
    """核算行程总花费并判定是否超预算：把 budget_check 写回 state（供前端预算条展示）、累计 retry_count，
    并回传 {budget_check, cut_suggestions} 供你查看。超支时 cut_suggestions 给出可削减的高价项；
    是否重排由你（agent）自主决定。"""
    retry_count = (state or {}).get("retry_count", 0) or 0
    res = compute_budget(day_plans, max(1, num_people), limit or 0.0, retry_count)
    advice = res["advice"] or {}
    budget_check = res["budget_check"]
    summary = {"budget_check": budget_check, "cut_suggestions": advice.get("cut_suggestions", [])}
    return Command(update={
        "budget_check": budget_check,
        "retry_count": res["retry_count"],
        "messages": [ToolMessage(
            json.dumps(summary, ensure_ascii=False), tool_call_id=tool_call_id)],
    })


@tool
async def finalize_plan(day_plans: list,
                        tool_call_id: Annotated[str, InjectedToolCallId],
                        state: Annotated[dict, InjectedState] = None) -> Command:
    """确认最终行程：写入 day_plans，并自动算出本轮变更的 changed_days 供前端增量重绘。
    完成规划或修改后调用一次。"""
    old = (state or {}).get("day_plans", []) or []
    changed = diff_changed_days(old, day_plans)
    old_ver = (state or {}).get("plan_version", 0) or 0
    new_ver = old_ver + (1 if changed else 0)
    return Command(update={
        "day_plans": day_plans,
        "changed_days": changed,
        "plan_version": new_ver,
        "messages": [ToolMessage(
            f"已确认行程，变更天数 {changed or '无'}", tool_call_id=tool_call_id)],
    })
