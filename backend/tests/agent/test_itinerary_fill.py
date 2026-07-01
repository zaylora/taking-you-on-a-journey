# -*- coding: utf-8 -*-
from app.agent.itinerary.fill import fill_day_plans, merge_safe_notes


def test_fill_day_plans_adds_weather_center_times_and_meals():
    skeleton = [{
        "day": 1,
        "items": [
            {
                "type": "attraction",
                "name": "祖庙",
                "poi_id": "p1",
                "location": {"lng": 113.11351, "lat": 23.028945},
                "start": "",
                "end": "",
                "indoor": False,
                "note": "",
                "cost": 0.0,
            },
            {
                "type": "attraction",
                "name": "岭南天地",
                "poi_id": "p2",
                "location": {"lng": 113.11519, "lat": 23.028895},
                "start": "",
                "end": "",
                "indoor": False,
                "note": "",
                "cost": 0.0,
            },
        ],
    }]
    restaurants = [
        {"name": "民信老铺", "poi_id": "r1", "lng": 113.114509, "lat": 23.031653, "type": "餐饮服务;甜品店"},
        {"name": "大良毋米粥", "poi_id": "r2", "lng": 113.2, "lat": 23.2, "type": "餐饮服务;中餐厅"},
    ]
    weather = {"text": "雷阵雨", "temp": "26~32℃", "is_rainy": True}
    centers = [{"lng": 113.11435, "lat": 23.02892}]

    out = fill_day_plans(
        skeleton=skeleton,
        restaurants=restaurants,
        weather=weather,
        daily_centers=centers,
        start_date="2026-07-01",
        num_people=1,
    )

    assert out[0]["date"] == "2026-07-01"
    assert out[0]["weather"] == weather
    assert out[0]["center"] == centers[0]
    assert [item["name"] for item in out[0]["items"] if item["type"] == "attraction"] == ["祖庙", "岭南天地"]
    assert any(item["type"] == "meal" and item["name"] == "民信老铺" for item in out[0]["items"])
    assert out[0]["items"][0]["start"] == "09:30"
    assert all(item["start"] <= item["end"] for item in out[0]["items"] if item["start"] and item["end"])


def test_fill_day_plans_does_not_invent_restaurants_when_candidates_empty():
    skeleton = [{
        "day": 1,
        "items": [{
            "type": "attraction",
            "name": "清晖园",
            "poi_id": "p1",
            "location": {"lng": 113.255086, "lat": 22.835613},
            "start": "",
            "end": "",
            "indoor": False,
            "note": "",
            "cost": 0.0,
        }],
    }]

    out = fill_day_plans(
        skeleton=skeleton,
        restaurants=[],
        weather={},
        daily_centers=[{"lng": 113.255086, "lat": 22.835613}],
        start_date="",
        num_people=1,
    )

    assert [item["type"] for item in out[0]["items"]] == ["attraction"]
    assert out[0]["items"][0]["name"] == "清晖园"


def test_fill_day_plans_adds_transport_between_attraction_and_meal():
    skeleton = [{
        "day": 1,
        "items": [
            {
                "type": "attraction",
                "name": "大佛寺",
                "poi_id": "p1",
                "location": {"lng": 113.2708, "lat": 23.1247},
                "start": "",
                "end": "",
                "indoor": False,
                "note": "",
                "cost": 0.0,
            },
            {
                "type": "attraction",
                "name": "永庆坊",
                "poi_id": "p2",
                "location": {"lng": 113.2440, "lat": 23.1156},
                "start": "",
                "end": "",
                "indoor": False,
                "note": "",
                "cost": 0.0,
            },
        ],
    }]
    restaurants = [{"name": "银记肠粉(北京路店)", "poi_id": "r1", "lng": 113.2705, "lat": 23.1239}]

    out = fill_day_plans(
        skeleton=skeleton,
        restaurants=restaurants,
        weather={},
        daily_centers=[{"lng": 113.2574, "lat": 23.1201}],
    )

    items = out[0]["items"]
    pairs = [(item.get("from"), item.get("to")) for item in items if item["type"] == "transport"]
    assert pairs == [
        ("大佛寺", "银记肠粉(北京路店)"),
        ("银记肠粉(北京路店)", "永庆坊"),
    ]
    assert [(item["type"], item["name"], item["start"], item["end"]) for item in items] == [
        ("attraction", "大佛寺", "09:30", "11:00"),
        ("transport", "", "11:00", "11:25"),
        ("meal", "银记肠粉(北京路店)", "12:00", "13:00"),
        ("transport", "", "13:00", "13:25"),
        ("attraction", "永庆坊", "13:25", "14:55"),
    ]


def test_merge_safe_notes_only_updates_matching_notes():
    base = [{
        "day": 1,
        "items": [
            {"type": "attraction", "name": "祖庙", "poi_id": "p1", "location": {"lng": 1, "lat": 2}, "note": "old"},
            {"type": "meal", "name": "民信老铺", "poi_id": "r1", "location": {"lng": 3, "lat": 4}, "note": "meal old"},
        ],
    }]
    enriched = [{
        "day": 1,
        "items": [
            {"type": "attraction", "name": "祖庙", "poi_id": "p1", "location": {"lng": 1, "lat": 2}, "note": "适合雨天慢逛。"},
            {"type": "meal", "name": "民信老铺", "poi_id": "r1", "location": {"lng": 3, "lat": 4}, "note": "meal new"},
        ],
    }]

    out = merge_safe_notes(base, enriched)

    assert out[0]["items"][0]["note"] == "适合雨天慢逛。"
    assert out[0]["items"][0]["location"] == {"lng": 1, "lat": 2}
    assert out[0]["items"][1]["note"] == "meal new"
    assert len(out[0]["items"]) == 2


def test_merge_safe_notes_returns_base_unchanged_when_structure_mismatches():
    base = [{
        "day": 1,
        "date": "2026-07-01",
        "weather": {"text": "晴", "temp": "", "is_rainy": False},
        "items": [
            {
                "type": "attraction",
                "name": "祖庙",
                "poi_id": "p1",
                "location": {"lng": 113.11351, "lat": 23.028945},
                "start": "09:30",
                "end": "11:00",
                "cost": 20.0,
                "note": "old",
            },
            {
                "type": "meal",
                "name": "民信老铺",
                "poi_id": "r1",
                "location": {"lng": 113.114509, "lat": 23.031653},
                "start": "12:00",
                "end": "13:00",
                "cost": 80.0,
                "note": "meal old",
            },
        ],
    }]
    enriched = [{
        **base[0],
        "items": [
            {**base[0]["items"][1], "note": "wrong order meal note"},
            {**base[0]["items"][0], "note": "wrong order attraction note"},
        ],
    }]

    out = merge_safe_notes(base, enriched)

    assert out == base


def test_merge_safe_notes_uses_item_index_for_duplicate_transport_notes():
    base = [{
        "day": 1,
        "items": [
            {
                "type": "transport",
                "name": "",
                "poi_id": "",
                "location": {"lng": 0.0, "lat": 0.0},
                "start": "11:00",
                "end": "11:25",
                "cost": 15.0,
                "weather": "",
                "note": "transport one",
            },
            {
                "type": "transport",
                "name": "",
                "poi_id": "",
                "location": {"lng": 0.0, "lat": 0.0},
                "start": "14:00",
                "end": "14:25",
                "cost": 15.0,
                "weather": "",
                "note": "transport two",
            },
        ],
    }]
    enriched = [{
        "day": 1,
        "items": [
            {**base[0]["items"][0], "note": "first ride"},
            {**base[0]["items"][1], "note": "second ride"},
        ],
    }]

    out = merge_safe_notes(base, enriched)

    assert [item["note"] for item in out[0]["items"]] == ["first ride", "second ride"]


def test_fill_day_plans_budget_advice_lowers_meal_and_transport_costs():
    skeleton = [{
        "day": 1,
        "items": [
            {
                "type": "attraction",
                "name": "祖庙",
                "poi_id": "p1",
                "location": {"lng": 113.11351, "lat": 23.028945},
                "start": "",
                "end": "",
                "indoor": False,
                "note": "",
                "cost": 0.0,
            },
            {
                "type": "attraction",
                "name": "岭南天地",
                "poi_id": "p2",
                "location": {"lng": 113.11519, "lat": 23.028895},
                "start": "",
                "end": "",
                "indoor": False,
                "note": "",
                "cost": 0.0,
            },
        ],
    }]
    restaurants = [{"name": "民信老铺", "poi_id": "r1", "lng": 113.114509, "lat": 23.031653}]

    default_out = fill_day_plans(
        skeleton=skeleton,
        restaurants=restaurants,
        weather={},
        daily_centers=[{"lng": 113.11435, "lat": 23.02892}],
    )
    budget_out = fill_day_plans(
        skeleton=skeleton,
        restaurants=restaurants,
        weather={},
        daily_centers=[{"lng": 113.11435, "lat": 23.02892}],
        budget_advice={"over_amount": 100.0},
    )

    default_meal = next(item for item in default_out[0]["items"] if item["type"] == "meal")
    budget_meal = next(item for item in budget_out[0]["items"] if item["type"] == "meal")
    default_transport = next(item for item in default_out[0]["items"] if item["type"] == "transport")
    budget_transport = next(item for item in budget_out[0]["items"] if item["type"] == "transport")
    assert budget_meal["cost"] < default_meal["cost"]
    assert budget_transport["cost"] < default_transport["cost"]
    assert "预算" in budget_meal["note"]
    assert "预算" in budget_transport["note"]
