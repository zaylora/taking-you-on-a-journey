# -*- coding: utf-8 -*-
"""工具调用进度文案生成。

这里不用额外 LLM 调用：进度提示必须比工具结果更快出现。基于工具参数生成短中文
文案，既能避免暴露内部函数名，也能让重复工具调用带上本次上下文。
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_MAX_PART_LEN = 28


def _clean(value: Any) -> str:
    """把工具参数压成适合 pill 展示的短文本。"""
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    elif isinstance(value, bool):
        text = "是" if value else "否"
    elif isinstance(value, int | float):
        text = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
    else:
        text = str(value)
    text = re.sub(r"\s+", " ", text.strip())
    return text[:_MAX_PART_LEN]


def _first_text(args: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = _clean(args.get(key))
        if value:
            return value
    return ""


def _keywords(value: Any) -> str:
    if isinstance(value, list):
        parts = [_clean(item) for item in value if _clean(item)]
        return "、".join(parts[:3])
    return _clean(value)


def _money(value: Any) -> str:
    amount = _clean(value)
    if not amount or amount == "0":
        return ""
    return f"{amount}元"


def _context(args: Mapping[str, Any]) -> str:
    city = _first_text(args, "city")
    return city or _first_text(args, "keyword", "keywords", "target", "user_id")


def _fallback_tool_label(args: Mapping[str, Any]) -> str:
    context = _context(args)
    return f"执行工具：{context}" if context else "执行工具"


def build_tool_label(name: str | None, args: Mapping[str, Any] | None = None) -> str:
    """根据工具名和本次参数生成短中文进度文案。"""
    tool_name = name or ""
    tool_args: Mapping[str, Any] = args if isinstance(args, Mapping) else {}

    if tool_name == "research_xhs_travel_guide":
        city = _first_text(tool_args, "city")
        days = _first_text(tool_args, "days")
        style = _first_text(tool_args, "travel_style")
        keywords = _keywords(tool_args.get("keywords"))
        subject = f"{city}{days + '天' if days else ''}{style}" or "旅行"
        return f"研究{subject}小红书攻略" + (f"：{keywords}" if keywords else "")

    if tool_name == "xhs_search_notes":
        keyword = _first_text(tool_args, "keyword")
        return "搜索小红书笔记" + (f"：{keyword}" if keyword else "")

    if tool_name == "xhs_read_note":
        target = _first_text(tool_args, "target")
        return "读取小红书笔记" + (f"：{target}" if target else "")

    if tool_name == "xhs_note_comments":
        target = _first_text(tool_args, "target")
        return "读取小红书评论" + (f"：{target}" if target else "")

    if tool_name == "xhs_hot_notes":
        category = _first_text(tool_args, "category") or "旅行"
        return f"浏览小红书热门：{category}"

    if tool_name == "xhs_user_profile":
        user_id = _first_text(tool_args, "user_id")
        return "读取小红书主页" + (f"：{user_id}" if user_id else "")

    if tool_name == "xhs_status":
        return "检查小红书登录状态"

    if tool_name == "search_attractions":
        city = _first_text(tool_args, "city")
        keywords = _first_text(tool_args, "keywords")
        base = f"搜索{city}景点" if city else "搜索景点"
        return base + (f"：{keywords}" if keywords else "")

    if tool_name == "search_restaurants":
        city = _first_text(tool_args, "city")
        keywords = _first_text(tool_args, "keywords")
        base = f"搜索{city}餐厅" if city else "搜索餐厅"
        return base + (f"：{keywords}" if keywords else "")

    if tool_name == "get_weather":
        city = _first_text(tool_args, "city")
        return f"查询{city}天气" if city else "查询天气"

    if tool_name == "plan_route":
        mode = _first_text(tool_args, "mode")
        return "规划交通" + (f"：{mode}" if mode else "")

    if tool_name == "assemble_itinerary":
        city = _first_text(tool_args, "city")
        days = _first_text(tool_args, "days")
        subject = f"{city}{days + '天' if days else ''}" or "逐日"
        return f"编排{subject}行程"

    if tool_name == "assign_hotels":
        city = _first_text(tool_args, "city")
        level = _first_text(tool_args, "level")
        subject = city or level
        return f"安排{subject}住宿" if subject else "安排住宿"

    if tool_name == "compute_budget_tool":
        people = _first_text(tool_args, "num_people")
        limit = _money(tool_args.get("limit"))
        subject = f"{people}人" if people else ""
        return f"核算{subject}预算" + (f"：{limit}" if limit else "")

    if tool_name == "finalize_plan":
        return "确认行程"

    if tool_name == "get_current_time":
        timezone = _first_text(tool_args, "timezone")
        return "获取当前时间" + (f"：{timezone}" if timezone else "")

    return _fallback_tool_label(tool_args)
