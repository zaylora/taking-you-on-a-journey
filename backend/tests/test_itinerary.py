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


def test_pick_nearest_selects_closest_and_respects_used():
    from app.graph.nodes.itinerary import pick_nearest
    pool = [
        {"name": "近", "poi_id": "A", "lng": 113.27, "lat": 23.14},
        {"name": "远", "poi_id": "B", "lng": 113.40, "lat": 23.30},
    ]
    anchor = {"lng": 113.27, "lat": 23.14}
    assert pick_nearest(pool, anchor, set())["poi_id"] == "A"
    assert pick_nearest(pool, anchor, {"A"})["poi_id"] == "B"
    assert pick_nearest(pool, anchor, {"A", "B"}) is None
    assert pick_nearest([], anchor, set()) is None


def test_build_day_stops_inserts_nearby_lunch_and_dinner():
    from app.graph.nodes.itinerary import build_day_stops
    attractions = [
        {"name": "A1", "poi_id": "A1", "lng": 113.27, "lat": 23.14},
        {"name": "A2", "poi_id": "A2", "lng": 113.33, "lat": 23.11},
    ]
    pool = [
        {"name": "饭A", "poi_id": "RA", "lng": 113.271, "lat": 23.141},  # 贴 A1
        {"name": "饭B", "poi_id": "RB", "lng": 113.331, "lat": 23.111},  # 贴 A2
    ]
    stops = build_day_stops(attractions, pool)
    assert [s["type"] for s in stops] == ["attraction", "meal", "attraction", "meal"]
    assert stops[0]["poi_id"] == "A1" and stops[2]["poi_id"] == "A2"
    assert stops[1]["poi_id"] == "RA"   # 午餐贴 A1
    assert stops[3]["poi_id"] == "RB"   # 晚餐贴 A2，且与午餐去重
    assert stops[1]["location"] == {"lng": 113.271, "lat": 23.141}


def test_build_day_stops_single_attraction_only_dinner():
    from app.graph.nodes.itinerary import build_day_stops
    stops = build_day_stops(
        [{"name": "A1", "poi_id": "A1", "lng": 113.27, "lat": 23.14}],
        [{"name": "饭A", "poi_id": "RA", "lng": 113.271, "lat": 23.141}],
    )
    assert [s["type"] for s in stops] == ["attraction", "meal"]


def test_build_day_stops_empty_attractions():
    from app.graph.nodes.itinerary import build_day_stops
    assert build_day_stops([], [{"name": "饭", "poi_id": "R", "lng": 1, "lat": 1}]) == []


# ---------------------------------------------------------------------------
# Task 5 — insert_transport + default_cost_by_mode
# ---------------------------------------------------------------------------

def test_default_cost_by_mode():
    from app.graph.nodes.itinerary import default_cost_by_mode
    assert default_cost_by_mode("步行", 0.5) == 0.0
    assert default_cost_by_mode("公交", 3.0) == 3.0
    assert default_cost_by_mode("驾车", 10.0) > default_cost_by_mode("驾车", 1.0)
    assert default_cost_by_mode("驾车", 10.0) == 22.0   # 钉死公式 2+2*km


def test_insert_transport_links_every_adjacent_pair():
    from app.graph.nodes.itinerary import insert_transport
    stops = [
        {"type": "attraction", "name": "越秀公园", "poi_id": "A1",
         "location": {"lng": 113.2656, "lat": 23.1401}},
        {"type": "attraction", "name": "广州塔", "poi_id": "A2",
         "location": {"lng": 113.3245, "lat": 23.1064}},
        {"type": "meal", "name": "饭", "poi_id": "R1",
         "location": {"lng": 113.325, "lat": 23.107}},
    ]
    out = insert_transport(stops)
    assert [it["type"] for it in out] == ["attraction", "transport", "attraction", "transport", "meal"]
    seg = out[1]
    assert seg["from"] == "越秀公园" and seg["to"] == "广州塔"
    assert seg["location"] == {"lng": 113.2656, "lat": 23.1401}  # 起点坐标=前点
    assert seg["mode"] == "驾车"   # ~7km
    assert out[3]["mode"] == "步行"  # 广州塔→饭 很近
    assert insert_transport(stops[:1]) == stops[:1]  # 单点不插段


# ---------------------------------------------------------------------------
# Task 6 — merge_soft_fields
# ---------------------------------------------------------------------------

def test_merge_soft_fields_only_copies_soft_keeps_geometry():
    from app.graph.nodes.itinerary import merge_soft_fields
    skeleton = [{
        "day": 1, "center": {"lng": 0, "lat": 0},
        "items": [
            {"type": "attraction", "name": "越秀公园", "poi_id": "A1",
             "location": {"lng": 113.27, "lat": 23.14}},
            {"type": "transport", "name": "", "from": "越秀公园", "to": "广州塔",
             "location": {"lng": 113.27, "lat": 23.14}, "mode": "驾车", "cost": 16.0},
            {"type": "attraction", "name": "广州塔", "poi_id": "A2",
             "location": {"lng": 113.32, "lat": 23.11}},
        ],
    }]
    # LLM 故意打乱顺序、改坐标、改 mode —— 都必须被丢弃
    llm = [{
        "day": 1,
        "items": [
            {"type": "attraction", "poi_id": "A2", "location": {"lng": 0, "lat": 0},
             "start": "14:00", "end": "16:00", "cost": 150.0, "indoor": True, "note": "登塔"},
            {"type": "attraction", "poi_id": "A1", "location": {"lng": 9, "lat": 9},
             "start": "09:00", "end": "11:00", "cost": 0.0, "note": "免费公园"},
            {"type": "transport", "mode": "步行", "cost": 0.0},
        ],
    }]
    out = merge_soft_fields(skeleton, llm)
    items = out[0]["items"]
    # 顺序与坐标来自骨架
    assert [it.get("poi_id", it["type"]) for it in items] == ["A1", "transport", "A2"]
    assert items[0]["location"] == {"lng": 113.27, "lat": 23.14}
    assert items[2]["location"] == {"lng": 113.32, "lat": 23.11}
    # 软字段来自 LLM
    assert items[0]["note"] == "免费公园" and items[0]["start"] == "09:00"
    assert items[2]["cost"] == 150.0 and items[2]["indoor"] is True
    # 交通段几何不动
    assert items[1]["mode"] == "驾车" and items[1]["cost"] == 16.0


def test_merge_soft_fields_tolerates_missing_llm_day():
    from app.graph.nodes.itinerary import merge_soft_fields
    skeleton = [{"day": 1, "center": {}, "items": [
        {"type": "attraction", "name": "X", "poi_id": "A1", "location": {"lng": 1, "lat": 1}}]}]
    out = merge_soft_fields(skeleton, [])   # LLM 全空 → 原样返回骨架
    assert out[0]["items"][0]["poi_id"] == "A1"
