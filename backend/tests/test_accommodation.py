import pytest
from app.graph.nodes import accommodation as acc_mod
from app.graph.nodes.accommodation import (
    accommodation, overnight_days, hotel_keyword, attach_hotels, _AccoResult, _HotelForDay,
)
from app.graph.nodes.itinerary import Hotel, Location


def test_overnight_days_excludes_last():
    assert overnight_days([{"day": 1}, {"day": 2}, {"day": 3}]) == [1, 2]
    assert overnight_days([{"day": 1}]) == []
    assert overnight_days([]) == []


def test_hotel_keyword_maps_levels():
    assert hotel_keyword("经济") == "经济型酒店"
    assert hotel_keyword("舒适") == "舒适型酒店"
    assert hotel_keyword("高端") == "高档酒店"
    assert hotel_keyword("未知") == "酒店"


def test_attach_hotels_merges_into_matching_day_without_mutating():
    dps = [{"day": 1, "items": []}, {"day": 2, "items": []}]
    out = attach_hotels(dps, [{"day": 1, "hotel": {"name": "如家", "price": 400}}])
    assert out[0]["hotel"]["name"] == "如家"
    assert "hotel" not in out[1]
    assert "hotel" not in dps[0]  # 不改原对象


@pytest.mark.asyncio
async def test_accommodation_assigns_hotels_to_overnight_days(fake_amap, monkeypatch):
    from tests.conftest import make_fake_build_llm
    fake_amap["search_poi"] = [{"name": "如家", "poi_id": "H1", "lng": 104.0, "lat": 30.6,
                                "address": "", "type": "住宿服务"}]
    result = _AccoResult(assignments=[
        _HotelForDay(day=1, hotel=Hotel(name="如家", poi_id="H1",
                                        location=Location(lng=104.0, lat=30.6),
                                        price=500.0, level="舒适"))])
    monkeypatch.setattr(acc_mod, "build_llm", make_fake_build_llm(structured=result))
    state = {"city": "成都", "preferences": {"住宿": "舒适"},
             "daily_centers": [{"lng": 104.0, "lat": 30.6}, {"lng": 104.1, "lat": 30.7}],
             "day_plans": [{"day": 1, "items": []}, {"day": 2, "items": []}]}
    out = await accommodation(state, None)
    dp = out["day_plans"]
    assert dp[0]["hotel"]["name"] == "如家" and dp[0]["hotel"]["price"] == 500.0
    assert "hotel" not in dp[1]  # 最后一天离程不住


@pytest.mark.asyncio
async def test_single_day_no_hotel(fake_amap, monkeypatch):
    from tests.conftest import make_fake_build_llm
    monkeypatch.setattr(acc_mod, "build_llm", make_fake_build_llm(structured=_AccoResult()))
    out = await accommodation({"city": "成都", "day_plans": [{"day": 1, "items": []}]}, None)
    assert out == {}


@pytest.mark.asyncio
async def test_poi_empty_still_produces_reference_hotel(fake_amap, monkeypatch):
    from tests.conftest import make_fake_build_llm
    fake_amap["search_poi"] = []  # POI 空 → 降级，仍交 LLM 生成参考酒店
    result = _AccoResult(assignments=[
        _HotelForDay(day=1, hotel=Hotel(name="参考酒店", price=300.0, level="经济"))])
    monkeypatch.setattr(acc_mod, "build_llm", make_fake_build_llm(structured=result))
    out = await accommodation({"city": "成都", "preferences": {"住宿": "经济"},
                               "daily_centers": [{"lng": 104.0, "lat": 30.6}],
                               "day_plans": [{"day": 1, "items": []}, {"day": 2, "items": []}]},
                              None)
    assert out["day_plans"][0]["hotel"]["name"] == "参考酒店"
