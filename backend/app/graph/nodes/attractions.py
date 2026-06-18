"""attractions 节点：高德 POI 检索景点。失败降级空列表，不阻断并行。"""
from app.tools import amap


async def attractions(state, config) -> dict:
    city = state.get("city", "")
    prefs = state.get("preferences", {}) or {}
    keywords = prefs.get("travel") or prefs.get("theme") or "热门景点"
    try:
        pois = await amap.search_poi(city, keywords, "风景名胜")
    except Exception:  # noqa: BLE001 —— 单节点降级，不阻断其余并行
        pois = []
    return {"attractions": pois}
