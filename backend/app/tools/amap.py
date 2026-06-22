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


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _enrich(p: dict) -> dict:
    """从高德 POI 提取 biz_ext 详情字段（extensions=all 时可用）。缺失给安全默认。"""
    biz = p.get("biz_ext") or {}
    return {
        "rating": _to_float(biz.get("rating")),
        "cost": _to_float(biz.get("cost")),
        "opentime": biz.get("opentime") or "",
        "typecode": p.get("typecode") or "",
    }


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
                "extensions": "all",
            })
            r.raise_for_status()
            data = r.json()
        out = []
        for p in data.get("pois", []) or []:
            loc = (p.get("location") or "").split(",")
            if len(loc) != 2:
                continue
            item = {
                "name": p.get("name", ""), "poi_id": p.get("id", ""),
                "lng": float(loc[0]), "lat": float(loc[1]),
                "address": p.get("address", ""), "type": p.get("type", ""),
            }
            item.update(_enrich(p))
            out.append(item)
        return out
    except Exception:  # noqa: BLE001
        return []


@traceable(run_type="tool", name="amap_search_around")
async def search_around(lng: float, lat: float, keywords: str, poi_type: str = "",
                        radius: int = 3000, page_size: int = 20) -> list[dict]:
    """围绕坐标的周边检索（高德 place/around，按距离排序）。结构同 search_poi。失败/空 []。"""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{_BASE}/place/around", params={
                "key": _key(), "location": f"{lng},{lat}", "keywords": keywords,
                "types": poi_type, "radius": radius, "offset": page_size,
                "sortrule": "distance", "extensions": "all",
            })
            r.raise_for_status()
            data = r.json()
        out = []
        for p in data.get("pois", []) or []:
            loc = (p.get("location") or "").split(",")
            if len(loc) != 2:
                continue
            item = {
                "name": p.get("name", ""), "poi_id": p.get("id", ""),
                "lng": float(loc[0]), "lat": float(loc[1]),
                "address": p.get("address", ""), "type": p.get("type", ""),
            }
            item.update(_enrich(p))
            out.append(item)
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
async def distance_batch(origins: list[tuple[float, float]],
                         dest: tuple[float, float]) -> list[float | None]:
    """高德 v3/distance：多起点->单终点，返回各起点到终点的秒数(type=1 驾车)。
    失败/缺失项为 None。origins 用 '|' 拼接，注意高德单次 origins 上限(约100)。
    """
    if not origins:
        return []
    origin_str = "|".join(f"{lng},{lat}" for lng, lat in origins)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{_BASE}/distance", params={
                "key": _key(), "origins": origin_str,
                "destination": f"{dest[0]},{dest[1]}", "type": "1",
            })
            r.raise_for_status()
            results = r.json().get("results") or []
        by_idx: dict[int, float] = {}
        for item in results:
            try:
                oid = int(item.get("origin_id", 0)) - 1  # 高德 origin_id 从 1 起
                by_idx[oid] = float(item.get("duration", 0))
            except (TypeError, ValueError):
                continue
        return [by_idx.get(i) for i in range(len(origins))]
    except Exception:  # noqa: BLE001 -- 降级：全 None，调用方用 haversine 兜底
        return [None] * len(origins)
