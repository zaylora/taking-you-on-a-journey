# -*- coding: utf-8 -*-
"""Current-time Agent tool."""
from langchain_core.tools import tool

from app.agent.time_context import CurrentTimeArgs, current_time_payload


@tool(args_schema=CurrentTimeArgs)
def get_current_time(timezone: str = "") -> dict:
    """获取当前真实时间。返回 {iso, timezone, unix_ms, date, time, weekday, utc_offset}。"""
    return current_time_payload(timezone or None)
