"""restaurants 节点：高德 POI 检索餐饮。失败降级空列表。"""
from app.tools import amap


async def restaurants(state, config) -> dict:
    city = state.get("city", "")
    prefs = state.get("preferences", {}) or {}
    keywords = prefs.get("food") or "美食"
    try:
        pois = await amap.search_poi(city, keywords, "餐饮")
    except Exception:  # noqa: BLE001
        pois = []
    return {"restaurants": pois}
