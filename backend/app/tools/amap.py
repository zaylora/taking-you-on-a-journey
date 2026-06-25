"""高德 Web 服务代理：统一 httpx.AsyncClient + 5s 超时 + 失败降级（不抛）。
Key 取自 config.amap_web_key，绝不下发前端、绝不进日志/SSE。
"""
import httpx
from langsmith import traceable

from app.core.config import get_settings

_BASE = "https://restapi.amap.com/v3"
_TIMEOUT = 5.0


def _key() -> str:
    return get_settings().amap_web_key.get_secret_value()


@traceable(run_type="tool", name="amap_geocode")
async def geocode(city: str) -> dict:
    """城市 → 中心坐标 {lng,lat}。失败降级 {}。"""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{_BASE}/geocode/geo", params={"key": _key(), "address": city})
            r.raise_for_status()
            data = r.json()
        loc = (data.get("geocodes") or [{}])[0].get("location")
        if not loc:
            return {}
        lng, lat = loc.split(",")
        return {"lng": float(lng), "lat": float(lat)}
    except Exception:  # noqa: BLE001 —— 降级
        return {}


@traceable(run_type="tool", name="amap_search_poi")
async def search_poi(city: str, keywords: str, poi_type: str = "", page_size: int = 20) -> list[dict]:
    """景点/餐厅候选。每项 name/poi_id/lng/lat/address/type。失败/空 []。"""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{_BASE}/place/text", params={
                "key": _key(), "city": city, "keywords": keywords,
                "types": poi_type, "offset": page_size, "citylimit": "true",
            })
            r.raise_for_status()
            data = r.json()
        out = []
        for p in data.get("pois", []) or []:
            loc = (p.get("location") or "").split(",")
            if len(loc) != 2:
                continue
            out.append({
                "name": p.get("name", ""), "poi_id": p.get("id", ""),
                "lng": float(loc[0]), "lat": float(loc[1]),
                "address": p.get("address", ""), "type": p.get("type", ""),
            })
        return out
    except Exception:  # noqa: BLE001
        return []


@traceable(run_type="tool", name="amap_get_weather")
async def get_weather(city: str) -> dict:
    """实时+预报；失败/远期降级季节气候文案。{text,temp,is_rainy,source}。"""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{_BASE}/weather/weatherInfo", params={
                "key": _key(), "city": city, "extensions": "all",
            })
            r.raise_for_status()
            data = r.json()
        casts = data.get("forecasts", [{}])[0].get("casts") or []
        if not casts:
            raise ValueError("no forecast")
        today = casts[0]
        text = today.get("dayweather", "")
        return {
            "text": text,
            "temp": f"{today.get('nighttemp','')}~{today.get('daytemp','')}℃",
            "is_rainy": "雨" in text,
            "source": "forecast",
        }
    except Exception:  # noqa: BLE001 —— 降级季节气候
        return {"text": "以当季气候为准", "temp": "", "is_rainy": False, "source": "climate"}


@traceable(run_type="tool", name="amap_plan_route")
async def plan_route(origin: str, dest: str, mode: str = "transit") -> dict:
    """大交通/市内交通方案；失败降级 {}。"""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{_BASE}/direction/transit/integrated", params={
                "key": _key(), "origin": origin, "destination": dest,
            })
            r.raise_for_status()
            return r.json().get("route", {}) or {}
    except Exception:  # noqa: BLE001
        return {}


@traceable(run_type="tool", name="amap_distance_batch")
async def distance_batch(origins: list[str], destination: str, type_: str = "1") -> list[dict]:
    """批量距离：origins(<=100 个 "lng,lat") -> destination。返回 [{origin_id,dest_id,distance,duration}]；失败 []。"""
    if not origins or not destination:
        return []
    origins = origins[:100]
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{_BASE}/distance", params={
                "key": _key(), "origins": "|".join(origins),
                "destination": destination, "type": type_,
            })
            r.raise_for_status()
            data = r.json()
        out = []
        for it in data.get("results", []) or []:
            out.append({
                "origin_id": int(it.get("origin_id", 0)),
                "dest_id": int(it.get("dest_id", 1)),
                "distance": float(it.get("distance", 0) or 0),
                "duration": float(it.get("duration", 0) or 0),
            })
        return out
    except Exception:  # noqa: BLE001 —— 降级
        return []
