# -*- coding: utf-8 -*-
"""ReAct Agent 工具箱。每个 tool = LLM 可调接口 + 内部确定性实现。

检索类直接复用 app/tools/amap.py（失败降级，不抛）。
编排/核算/收尾类见后续步骤；ask_user 经 interrupt 暂停。
"""
from langchain_core.tools import tool

from app.tools import amap


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
