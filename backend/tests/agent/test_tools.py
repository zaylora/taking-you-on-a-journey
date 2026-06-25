# -*- coding: utf-8 -*-
import pytest

from app.agent import tools


@pytest.mark.asyncio
async def test_search_attractions_returns_pois(fake_amap):
    fake_amap["search_poi"] = [{"name": "故宫", "poi_id": "p1", "lng": 116.4, "lat": 39.9}]
    out = await tools.search_attractions.ainvoke({"city": "北京", "keywords": "热门景点"})
    assert out[0]["name"] == "故宫"


@pytest.mark.asyncio
async def test_search_attractions_degrades_to_empty(fake_amap, monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("amap down")
    monkeypatch.setattr("app.tools.amap.search_poi", _boom)
    out = await tools.search_attractions.ainvoke({"city": "北京", "keywords": "x"})
    assert out == []


@pytest.mark.asyncio
async def test_get_weather_tool(fake_amap):
    out = await tools.get_weather.ainvoke({"city": "成都"})
    assert out["text"] == "多云"
