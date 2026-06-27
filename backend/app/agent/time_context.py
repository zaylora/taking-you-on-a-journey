# -*- coding: utf-8 -*-
"""当前时间上下文：动态 system prompt 注入 + Agent 可调用时间工具。"""
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain_core.messages import SystemMessage
from pydantic import BaseModel, Field

from app.agent.prompt import TRIP_AGENT_SYS
from app.core.config import get_settings


WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _resolve_timezone(timezone_name: str | None = None) -> tuple[str, ZoneInfo]:
    configured = timezone_name or get_settings().agent_timezone
    try:
        return configured, ZoneInfo(configured)
    except ZoneInfoNotFoundError:
        return "UTC", ZoneInfo("UTC")


def current_time_payload(timezone_name: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    """返回给工具和 prompt 共用的当前时间结构。"""
    tz_name, tz = _resolve_timezone(timezone_name)
    current = now.astimezone(tz) if now else datetime.now(tz)
    offset = current.strftime("%z")
    utc_offset = f"{offset[:3]}:{offset[3:]}" if offset else ""
    return {
        "iso": current.isoformat(timespec="seconds"),
        "timezone": tz_name,
        "unix_ms": int(current.timestamp() * 1000),
        "date": current.date().isoformat(),
        "time": current.strftime("%H:%M:%S"),
        "weekday": WEEKDAYS[current.weekday()],
        "utc_offset": utc_offset,
    }


def build_system_prompt(timezone_name: str | None = None, now: datetime | None = None) -> str:
    """每次模型调用前生成带当前时间快照的系统提示。"""
    payload = current_time_payload(timezone_name=timezone_name, now=now)
    time_context = (
        "\n\n当前时间上下文：\n"
        f"- 当前日期: {payload['date']}\n"
        f"- 当前时间: {payload['time']}\n"
        f"- 星期: {payload['weekday']}\n"
        f"- 时区: {payload['timezone']} (UTC{payload['utc_offset']})\n"
        f"- Unix 毫秒: {payload['unix_ms']}\n"
        "如果用户问题依赖准确的当前时间、日期、时区或相对时间表达，"
        "先调用已注册的当前时间工具；不要凭历史消息或模型记忆推断。"
    )
    return f"{TRIP_AGENT_SYS}{time_context}"


class CurrentTimeArgs(BaseModel):
    """当前时间工具输入。"""

    timezone: str = Field(
        default="",
        description="IANA 时区名，如 Asia/Shanghai、America/New_York；为空则使用系统默认时区。",
    )


class CurrentTimePromptMiddleware(AgentMiddleware):
    """把当前时间快照注入每一次模型调用的 system message。"""

    def wrap_model_call(self, request: ModelRequest, handler):
        request = request.override(system_message=SystemMessage(content=build_system_prompt()))
        return handler(request)

    async def awrap_model_call(self, request: ModelRequest, handler):
        request = request.override(system_message=SystemMessage(content=build_system_prompt()))
        return await handler(request)
