"""apply_operations 住宿重算 + 预算重算 + city 闭环测试（Task 6 TDD）。"""
import pytest

from app.planning.apply import apply_operations
from app.graph.nodes.itinerary import insert_transport
from tests.conftest import make_fake_build_llm


def _plan():
    """构造 2 天行程（带交通段）供测试复用。"""
    day1 = [{"type": "attraction", "name": "A", "poi_id": "B1",
             "location": {"lng": 104.05, "lat": 30.65}, "cost": 60.0}]
    day2 = [{"type": "attraction", "name": "B", "poi_id": "B2",
             "location": {"lng": 104.04, "lat": 30.67}, "cost": 60.0}]
    return [{"day": 1, "items": insert_transport(day1), "center": {"lng": 104.05, "lat": 30.65}},
            {"day": 2, "items": insert_transport(day2), "center": {"lng": 104.04, "lat": 30.67}}]


@pytest.mark.asyncio
async def test_apply_set_budget_recomputes_budget_check():
    """set_budget op 应触发预算重算，输出 budget + budget_check（含 limit/estimated）。"""
    state = {"day_plans": _plan(), "plan_version": 1, "num_people": 1, "budget": 5000}
    out = await apply_operations([{"op": "set_budget", "amount": 3000.0}], {}, state)
    assert out["budget"] == 3000.0
    assert out["budget_check"]["limit"] == 3000.0
    assert "estimated" in out["budget_check"]


@pytest.mark.asyncio
async def test_apply_set_hotel_reassigns_hotels(monkeypatch, fake_amap):
    """set_hotel op 应触发住宿重算，过夜日（第 1 天）嵌入 LLM 返回的酒店。"""
    from app.graph.nodes import accommodation as acc
    monkeypatch.setattr(acc, "build_llm", make_fake_build_llm(
        structured=acc._AccoResult(assignments=[
            acc._HotelForDay(day=1, hotel=acc.Hotel(name="测试酒店", poi_id="H1",
                                                    location=acc.Location(lng=104.05, lat=30.65),
                                                    price=400.0))])))
    state = {"day_plans": _plan(), "plan_version": 1, "city": "成都", "num_people": 1,
             "budget": 5000, "daily_centers": [{"lng": 104.05, "lat": 30.65}]}
    out = await apply_operations([{"op": "set_hotel", "criteria": "离地铁近"}], {}, state)
    assert out["day_plans"][0].get("hotel", {}).get("name") == "测试酒店"   # 过夜日(第1天)嵌入酒店


@pytest.mark.asyncio
async def test_apply_set_region_uses_normalized_req_city_when_top_missing(fake_amap, monkeypatch):
    """city 闭环：顶层 state 无 city 时，set_region 的 geocode 应从 normalized_req/requirements_patch 读到城市名。"""
    import app.tools.amap as amap
    captured = {}

    async def _geo(addr):
        captured["addr"] = addr
        return {"lng": 113.46, "lat": 23.10}

    monkeypatch.setattr(amap, "geocode", _geo)
    fake_amap["search_around"] = [
        {"name": "黄埔军校旧址", "poi_id": "H1", "lng": 113.47, "lat": 23.09, "type": "风景名胜"}]
    day1 = [{"type": "attraction", "name": "越秀公园", "poi_id": "G1",
             "location": {"lng": 113.27, "lat": 23.13}}]
    state = {"day_plans": [{"day": 1, "items": insert_transport(day1),
                            "center": {"lng": 113.27, "lat": 23.13}}],
             "plan_version": 1, "normalized_req": {"city": "广州"}}   # 顶层无 city
    op = {"op": "set_region", "day": 1, "area": "黄埔", "requirements_patch": {"city": "广州"}}
    out = await apply_operations([op], {}, state)
    assert "广州" in captured["addr"]   # geocode 用了补救的 city，而非空字符串
    assert out["changed_days"] == [1]
