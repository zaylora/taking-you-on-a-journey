# -*- coding: utf-8 -*-
from app.agent.itinerary.fill import fill_day_plans


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
