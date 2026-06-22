"""Tavily 联网检索工具：封装为 LangChain 工具，供编排 agent 按需调用。

Key 取自 config.tavily_api_key（SecretStr），绝不下发前端/进日志。未配 key
时返回 None，调用方据此降级（不联网）。
"""
import os

from app.core.config import get_settings


def build_tavily_tool(max_results: int = 3):
    """返回一个可被 agent / bind_tools 使用的 Tavily 检索工具；未配 key 返回 None。"""
    key = get_settings().tavily_api_key.get_secret_value()
    if not key:
        return None
    # langchain_tavily 通过环境变量读取 key
    os.environ.setdefault("TAVILY_API_KEY", key)
    from langchain_tavily import TavilySearch
    return TavilySearch(max_results=max_results)
