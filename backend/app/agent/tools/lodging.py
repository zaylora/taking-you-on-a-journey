# -*- coding: utf-8 -*-
"""Lodging assignment Agent tool."""
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field, field_validator

from app.agent.itinerary.lodging import (
    ACCO_SYS, _AccoResult, attach_hotels, hotel_keyword, overnight_days,
)
from app.llm.factory import build_llm
from app.utils import amap

from .utils import parse_jsonish_string


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
        return parse_jsonish_string(value)


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
