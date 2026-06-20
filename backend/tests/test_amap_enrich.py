import pytest

from app.tools import amap


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        # 断言开启了详情扩展
        assert params.get("extensions") == "all"
        return _FakeResp(self._payload)


_PAYLOAD = {
    "pois": [{
        "name": "广州塔", "id": "B001", "location": "113.32,23.10",
        "address": "海珠区", "type": "风景名胜", "typecode": "110000",
        "biz_ext": {"rating": "4.6", "cost": "150", "opentime": "09:00-22:00"},
    }]
}


@pytest.fixture
def patch_client(monkeypatch):
    monkeypatch.setattr(amap, "_key", lambda: "k")
    monkeypatch.setattr(amap.httpx, "AsyncClient",
                        lambda *a, **k: _FakeClient(_PAYLOAD))


async def test_search_poi_parses_biz_ext(patch_client):
    out = await amap.search_poi("广州", "塔")
    assert out[0]["rating"] == 4.6
    assert out[0]["cost"] == 150.0
    assert out[0]["opentime"] == "09:00-22:00"
    assert out[0]["typecode"] == "110000"


async def test_search_poi_defaults_when_biz_ext_missing(monkeypatch):
    monkeypatch.setattr(amap, "_key", lambda: "k")
    payload = {"pois": [{"name": "X", "id": "B002", "location": "113.0,23.0"}]}
    monkeypatch.setattr(amap.httpx, "AsyncClient",
                        lambda *a, **k: _FakeClient(payload))
    out = await amap.search_poi("广州", "x")
    assert out[0]["rating"] == 0.0
    assert out[0]["cost"] == 0.0
    assert out[0]["opentime"] == ""
    assert out[0]["typecode"] == ""
