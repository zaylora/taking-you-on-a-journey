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
