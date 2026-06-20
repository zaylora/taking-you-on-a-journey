import pytest
from app.graph.nodes import itinerary as it_mod
from app.graph.nodes.itinerary import DayPlans, DayPlan, PlanItem, Location, DayWeather


@pytest.mark.asyncio
async def test_itinerary_produces_day_plans(monkeypatch):
    from tests.conftest import make_fake_build_llm
    fake = DayPlans(days=[DayPlan(
        day=1, date="2026-07-01",
        weather=DayWeather(text="多云", temp="24~31℃", is_rainy=False),
        center=Location(lng=104.06, lat=30.65),
        items=[PlanItem(type="attraction", name="武侯祠", poi_id="B1",
                        location=Location(lng=104.04, lat=30.64),
                        start="09:00", end="11:00", indoor=False, note="三国文化")],
    )])
    monkeypatch.setattr(it_mod, "build_llm", make_fake_build_llm(structured=fake))
    state = {"days": 1, "attractions": [{"name": "武侯祠", "poi_id": "B1", "lng": 104.04, "lat": 30.64}],
             "restaurants": [], "transport": {}, "weather": {"is_rainy": False}}
    out = await it_mod.itinerary(state, None)
    dp = out["day_plans"]
    assert dp[0]["day"] == 1
    assert dp[0]["items"][0]["name"] == "武侯祠"
    assert "center" in dp[0]
    assert len(out["daily_centers"]) == 1


def test_plan_item_and_hotel_carry_cost_and_hotel():
    from app.graph.nodes.itinerary import PlanItem, Hotel, DayPlan, Location
    item = PlanItem(type="attraction", name="武侯祠", poi_id="B1",
                    location=Location(lng=104.0, lat=30.6), cost=60.0)
    assert item.cost == 60.0
    hotel = Hotel(name="如家", poi_id="H1", location=Location(lng=104.0, lat=30.6),
                  price=400.0, level="舒适")
    dp = DayPlan(day=1, center=Location(), items=[item], hotel=hotel)
    dumped = dp.model_dump(by_alias=True)
    assert dumped["items"][0]["cost"] == 60.0
    assert dumped["hotel"]["price"] == 400.0
    assert DayPlan(day=2, center=Location(), items=[]).hotel is None
    assert Hotel().price == 0.0 and Hotel().model_dump()["name"] == ""


def test_build_payload_injects_budget_advice():
    from app.graph.nodes.itinerary import _build_payload
    base = {"days": 2, "num_people": 2}
    assert "budget_advice" not in _build_payload(base, [])
    with_advice = {**base, "budget_advice": {"over_amount": 500.0, "cut_suggestions": []}}
    p = _build_payload(with_advice, [])
    assert p["budget_advice"]["over_amount"] == 500.0
    assert p["num_people"] == 2


def test_haversine_km_known_distance():
    from app.graph.nodes.itinerary import haversine_km
    # 越秀公园 → 广州塔 直线约 7km
    d = haversine_km({"lng": 113.2656, "lat": 23.1401}, {"lng": 113.3245, "lat": 23.1064})
    assert 6.0 < d < 8.0
    assert haversine_km({"lng": 113.0, "lat": 23.0}, {"lng": 113.0, "lat": 23.0}) == 0.0


def test_mode_by_distance_boundaries():
    from app.graph.nodes.itinerary import mode_by_distance
    assert mode_by_distance(0.9) == "步行"
    assert mode_by_distance(1.0) == "公交"
    assert mode_by_distance(4.9) == "公交"
    assert mode_by_distance(5.0) == "驾车"
    assert mode_by_distance(7.1) == "驾车"
