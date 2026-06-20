from app.graph.nodes.time_budget import (
    DAY_BUDGET, attraction_minutes, transit_minutes, day_used_minutes,
)


def test_day_budget_default():
    assert DAY_BUDGET == 480


def test_attraction_minutes_uses_visit_minutes():
    assert attraction_minutes({"visit_minutes": 200}) == 200


def test_attraction_minutes_falls_back_to_type():
    assert attraction_minutes({"type": "博物馆"}) == 150
    assert attraction_minutes({"type": "公园"}) == 120


def test_attraction_minutes_default_90():
    assert attraction_minutes({"name": "某不知名地"}) == 90


def test_transit_minutes_walk():
    # 1.2km 步行 @12km/h = 6 分钟
    assert transit_minutes(1.2, "步行") == 6


def test_transit_minutes_drive():
    # 15km 驾车 @30km/h = 30 分钟
    assert transit_minutes(15.0, "驾车") == 30


def test_day_used_minutes_sums_all():
    items = [
        {"type": "attraction", "visit_minutes": 120,
         "location": {"lng": 113.0, "lat": 23.0}},
        {"type": "transport", "mode": "步行",
         "location": {"lng": 113.0, "lat": 23.0}},
        {"type": "meal", "location": {"lng": 113.01, "lat": 23.0}},
        {"type": "transport", "mode": "公交",
         "location": {"lng": 113.01, "lat": 23.0}},
        {"type": "attraction", "visit_minutes": 90,
         "location": {"lng": 113.05, "lat": 23.0}},
    ]
    used = day_used_minutes(items)
    # 景点 120 + 90，午餐 60，两段交通 > 0
    assert used >= 120 + 90 + 60
    assert used < 600
