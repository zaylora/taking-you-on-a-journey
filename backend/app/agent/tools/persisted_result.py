# -*- coding: utf-8 -*-
"""读取已落盘的大工具结果。"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.tool_result_storage import read_persisted_tool_result_slice
from app.core.config import get_settings


class ReadPersistedToolResultArgs(BaseModel):
    """落盘工具结果分页读取参数。"""

    result_id: str = Field(description="工具返回的 result_id，例如 xhs_read_note-call_abc.json。")
    offset: int = Field(default=0, ge=0, description="从第几个字符开始读取，默认 0。")
    limit: int = Field(default=4000, ge=1, le=12000, description="最多读取多少字符。")


@tool(args_schema=ReadPersistedToolResultArgs)
async def read_persisted_tool_result(result_id: str, offset: int = 0, limit: int = 4000) -> dict:
    """按 result_id 分页读取已落盘的大工具结果。只能读取后端配置目录内的结果文件。"""
    settings = get_settings()
    return read_persisted_tool_result_slice(
        result_id,
        offset=offset,
        limit=limit,
        storage_dir=settings.tool_result_storage_dir,
    )
