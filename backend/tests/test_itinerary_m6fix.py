import pytest

from app.graph.nodes.itinerary import itinerary
from app.graph.nodes.time_budget import day_used_minutes, DAY_BUDGET


def _a(name, lng, lat, rating=4.0, vm=120):
    return {"name": name, "poi_id": name, "lng": lng, "lat": lat,
            "rating": rating, "visit_minutes": vm}


class _FakeLLM:
    """构造成功，但 ainvoke 抛错——模拟 LLM 软填失败，走骨架默认（在节点 try 内）。"""
    def with_structured_output(self, *a, **k):
        return self

    async def ainvoke(self, *a, **k):
        raise RuntimeError("offline")


@pytest.fixture
def no_llm_no_amap(monkeypatch):
    # 断网：LLM 软填抛错走骨架默认；周边餐饮搜索返回空
    import app.graph.nodes.itinerary as it
    from app.itinerary import soft_fill as sf

    monkeypatch.setattr(sf, "build_llm", lambda *a, **k: _FakeLLM())

    async def _empty(*a, **k):
        return []

    monkeypatch.setattr(it.amap, "search_around", _empty)


async def test_each_day_within_budget(no_llm_no_amap):
    # 10 个景点、2 天 → 预选+复校后每天不超预算
    attractions = [_a(f"p{i}", 113.0 + i * 0.01, 23.0) for i in range(10)]
    out = await itinerary({"days": 2, "attractions": attractions}, config={})
    for day in out["day_plans"]:
        assert day_used_minutes(day["items"]) <= DAY_BUDGET


async def test_each_day_within_budget_with_meals_and_transit(monkeypatch):
    # 诚实场景：真实餐厅池（每天插午/晚餐）+ 地理分散景点，断言真实 day_used_minutes 不超预算。
    # 守护 review Critical：rebalance 预算闸门须与 day_used_minutes 同口径（含餐饮+交通）。
    import app.graph.nodes.itinerary as it
    from app.itinerary import soft_fill as sf

    monkeypatch.setattr(sf, "build_llm", lambda *a, **k: _FakeLLM())

    async def _pool(lng, lat, *a, **k):
        # 在当天中心附近返回一家餐厅，使 build_day_stops 真插午/晚餐
        return [{"name": "餐厅", "poi_id": f"r{lng:.3f}", "lng": lng + 0.002, "lat": lat + 0.002}]

    monkeypatch.setattr(it.amap, "search_around", _pool)

    # 跨度较大的景点（驾车/公交段产生真实交通耗时）
    attractions = [_a(f"p{i}", 113.0 + i * 0.05, 23.0 + (i % 3) * 0.04, vm=120) for i in range(12)]
    out = await itinerary({"days": 3, "attractions": attractions}, config={})
    for day in out["day_plans"]:
        assert day_used_minutes(day["items"]) <= DAY_BUDGET


async def test_reports_dropped(no_llm_no_amap):
    attractions = [_a(f"p{i}", 113.0 + i * 0.01, 23.0, vm=120) for i in range(10)]
    out = await itinerary({"days": 1, "attractions": attractions}, config={})
    # 1 天 480min，每个 160min → 最多 3 个，其余进 dropped
    assert len(out["dropped_attractions"]) > 0
    assert all("reason" in d for d in out["dropped_attractions"])


async def test_transport_invariant_kept(no_llm_no_amap):
    # M6 不变量：相邻停靠点之间恰好一个 transport
    attractions = [_a(f"p{i}", 113.0 + i * 0.01, 23.0) for i in range(6)]
    out = await itinerary({"days": 2, "attractions": attractions}, config={})
    for day in out["day_plans"]:
        items = day["items"]
        stops = [i for i in items if i.get("type") != "transport"]
        transports = [i for i in items if i.get("type") == "transport"]
        if len(stops) >= 2:
            assert len(transports) == len(stops) - 1
