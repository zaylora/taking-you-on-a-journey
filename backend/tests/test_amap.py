import httpx
import pytest

import app.tools.amap as amap


class _FakeResp:
    def __init__(self, data): self._data = data
    def json(self): return self._data
    def raise_for_status(self): pass


def _patch_client(monkeypatch, *, payload=None, exc=None):
    class _FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k):
            if exc: raise exc
            return _FakeResp(payload)
    monkeypatch.setattr(amap.httpx, "AsyncClient", _FakeClient)


@pytest.mark.asyncio
async def test_geocode_ok(monkeypatch):
    _patch_client(monkeypatch, payload={"status": "1", "geocodes": [{"location": "104.06,30.65"}]})
    assert await amap.geocode("成都") == {"lng": 104.06, "lat": 30.65}


@pytest.mark.asyncio
async def test_geocode_degrades_on_timeout(monkeypatch):
    _patch_client(monkeypatch, exc=httpx.TimeoutException("t"))
    assert await amap.geocode("成都") == {}


@pytest.mark.asyncio
async def test_search_poi_degrades_on_error(monkeypatch):
    _patch_client(monkeypatch, exc=httpx.ConnectError("x"))
    assert await amap.search_poi("成都", "景点", "风景名胜") == []


@pytest.mark.asyncio
async def test_get_weather_degrades_to_climate(monkeypatch):
    _patch_client(monkeypatch, exc=httpx.TimeoutException("t"))
    w = await amap.get_weather("成都")
    assert w["source"] == "climate" and "is_rainy" in w


@pytest.mark.asyncio
async def test_search_around_ok(monkeypatch):
    _patch_client(monkeypatch, payload={"status": "1", "pois": [
        {"name": "陶陶居", "id": "R1", "location": "113.2617,23.1336",
         "address": "解放北路", "type": "餐饮服务"},
    ]})
    out = await amap.search_around(113.2656, 23.1401, "美食", "餐饮")
    assert out == [{"name": "陶陶居", "poi_id": "R1", "lng": 113.2617, "lat": 23.1336,
                    "address": "解放北路", "type": "餐饮服务",
                    "rating": 0.0, "cost": 0.0, "opentime": "", "typecode": ""}]


@pytest.mark.asyncio
async def test_search_around_degrades_on_error(monkeypatch):
    _patch_client(monkeypatch, exc=httpx.ConnectError("x"))
    assert await amap.search_around(113.26, 23.14, "美食", "餐饮") == []
