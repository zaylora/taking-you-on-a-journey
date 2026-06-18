"""weather 节点：调高德天气，失败由 tool 层降级。"""
from app.tools import amap


async def weather(state, config) -> dict:
    return {"weather": await amap.get_weather(state.get("city", ""))}
