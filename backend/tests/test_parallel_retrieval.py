import pytest
from app.graph.nodes.weather import weather
from app.graph.nodes.attractions import attractions
from app.graph.nodes.restaurants import restaurants
from app.graph.nodes.transport import transport


@pytest.mark.asyncio
async def test_each_node_writes_its_field(fake_amap):
    fake_amap["search_poi"] = [{"name": "武侯祠", "poi_id": "B1", "lng": 104.0, "lat": 30.6,
                                "address": "", "type": "风景名胜"}]
    st = {"city": "成都", "preferences": {"food": "辣"}, "days": 3}
    assert "weather" in await weather(st, None)
    a = await attractions(st, None)
    assert a["attractions"][0]["name"] == "武侯祠"
    assert "restaurants" in await restaurants(st, None)
    assert "transport" in await transport(st, None)


@pytest.mark.asyncio
async def test_single_node_failure_degrades_not_raises(fake_amap, monkeypatch):
    import app.tools.amap as amap
    async def _boom(*a, **k): raise RuntimeError("amap down")
    monkeypatch.setattr(amap, "search_poi", _boom)
    out = await attractions({"city": "成都", "preferences": {}}, None)
    assert out == {"attractions": []}  # 降级空列表，不抛
