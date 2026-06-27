# -*- coding: utf-8 -*-
"""旅行规划 Agent 使用的 LangChain tools。"""
import re
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.tools import amap

_KEYWORD_SPLIT_RE = re.compile(r"[\s,，、;；/|]+")
_SEARCH_MIN_RESULTS = 3
_SEARCH_MAX_RESULTS = 20
_SEARCH_FALLBACK_TERMS = 6


def _split_search_keywords(keywords: str) -> list[str]:
    terms = []
    seen = set()
    for term in _KEYWORD_SPLIT_RE.split((keywords or "").strip()):
        term = term.strip()
        if len(term) < 2 or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def _poi_key(poi: dict[str, Any]) -> str:
    return str(poi.get("poi_id") or f"{poi.get('name', '')}|{poi.get('address', '')}")


def _merge_pois(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = []
    seen = set()
    for group in groups:
        for poi in group or []:
            key = _poi_key(poi)
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(poi)
            if len(merged) >= _SEARCH_MAX_RESULTS:
                return merged
    return merged


async def _search_poi_with_keyword_fallback(city: str, keywords: str, poi_type: str) -> list[dict[str, Any]]:
    results = _merge_pois(await amap.search_poi(city, keywords, poi_type))
    if len(results) >= _SEARCH_MIN_RESULTS:
        return results

    terms = _split_search_keywords(keywords)
    if len(terms) <= 1:
        return results

    for term in terms[:_SEARCH_FALLBACK_TERMS]:
        more = await amap.search_poi(city, term, poi_type, page_size=10)
        results = _merge_pois(results, more)
        if len(results) >= _SEARCH_MIN_RESULTS:
            break
    return results


class SearchAttractionsArgs(BaseModel):
    """景点检索工具输入。字段说明会暴露给模型用于生成工具调用参数。"""

    city: str = Field(
        description=(
            "高德检索城市，优先传地级市或高德可识别城市名，如 广州、佛山；"
            "不要把多个城市合在一起。行政区可放入 keywords 辅助限定，如 顺德热门景点。"
        )
    )
    keywords: str = Field(
        default="热门景点",
        description=(
            "景点检索关键词。优先使用短关键词，如 热门景点、顺德热门景点、清晖园；"
            "不要一次塞很多景点名。多个明确 POI 应分多次调用，本工具会在低命中时自动拆词补查。"
        ),
    )


class SearchRestaurantsArgs(BaseModel):
    """餐厅检索工具输入。字段说明会暴露给模型用于生成工具调用参数。"""

    city: str = Field(
        description=(
            "高德检索城市，优先传地级市或高德可识别城市名，如 广州、佛山；"
            "不要把多个城市合在一起。行政区可放入 keywords 辅助限定，如 顺德美食。"
        )
    )
    keywords: str = Field(
        default="美食",
        description=(
            "餐厅检索关键词。优先使用短关键词，如 美食、早茶、顺德美食、双皮奶；"
            "不要一次塞很多店名。多个明确餐厅应分多次调用，本工具会在低命中时自动拆词补查。"
        ),
    )


class PlanRouteArgs(BaseModel):
    """路径规划工具输入。字段说明会暴露给模型用于生成工具调用参数。"""

    origin: str = Field(
        description=(
            "起点坐标字符串，必须是高德坐标 \"lng,lat\" 格式，如 "
            "\"116.481499,39.990475\"。优先从 POI 返回或 day_plans 中的 "
            "lng/lat 拼接；不要传地名、POI 名称或地址。"
        )
    )
    dest: str = Field(
        description=(
            "终点坐标字符串，必须是高德坐标 \"lng,lat\" 格式，如 "
            "\"116.465063,39.999538\"。优先从 POI 返回或 day_plans 中的 "
            "lng/lat 拼接；不要传地名、POI 名称或地址。"
        )
    )
    mode: str = Field(
        default="transit",
        description="交通方式，默认 transit；当前后端按高德公交路径规划请求处理。",
    )


@tool(args_schema=SearchAttractionsArgs)
async def search_attractions(city: str, keywords: str = "热门景点") -> list:
    """检索城市景点 POI。返回 [{name,poi_id,lng,lat,address,type}]；失败或无结果返回 []。
    传参限制：city 优先用地级市；keywords 用短关键词，多个 POI 不要一次塞入同一参数。"""
    try:
        return await _search_poi_with_keyword_fallback(city, keywords, "风景名胜")
    except Exception:  # noqa: BLE001 -- 降级，交 LLM 决策
        return []


@tool(args_schema=SearchRestaurantsArgs)
async def search_restaurants(city: str, keywords: str = "美食") -> list:
    """检索城市餐饮 POI。返回 [{name,poi_id,lng,lat,...}]；失败或无结果返回 []。
    传参限制：city 优先用地级市；keywords 用短关键词，多个餐厅不要一次塞入同一参数。"""
    try:
        return await _search_poi_with_keyword_fallback(city, keywords, "餐饮")
    except Exception:  # noqa: BLE001
        return []


@tool
async def get_weather(city: str) -> dict:
    """查询城市天气。返回 {text,temp,is_rainy,source}；失败降级季节气候。"""
    try:
        return await amap.get_weather(city)
    except Exception:  # noqa: BLE001
        return {"text": "以当季气候为准", "temp": "", "is_rainy": False, "source": "climate"}


@tool(args_schema=PlanRouteArgs)
async def plan_route(origin: str, dest: str, mode: str = "transit") -> dict:
    """规划两地交通方案。origin/dest 必须传 "lng,lat" 坐标字符串；失败降级 {}。"""
    try:
        return await amap.plan_route(origin, dest, mode)
    except Exception:  # noqa: BLE001
        return {}
