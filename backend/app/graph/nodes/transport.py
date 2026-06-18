"""transport 节点：高德路径规划。无明确起终点则返回空，由 itinerary 降级。"""
from app.tools import amap


async def transport(state, config) -> dict:
    city = state.get("city", "")
    try:
        route = await amap.plan_route(city, city) if city else {}
    except Exception:  # noqa: BLE001
        route = {}
    return {"transport": route}
