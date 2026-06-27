from app.agent.itinerary.lodging import overnight_days, attach_hotels, hotel_keyword


def test_overnight_days_excludes_last():
    dps = [{"day": 1, "items": []}, {"day": 2, "items": []}, {"day": 3, "items": []}]
    assert overnight_days(dps) == [1, 2]


def test_overnight_single_day_none():
    assert overnight_days([{"day": 1, "items": []}]) == []


def test_attach_hotels_embeds_by_day():
    dps = [{"day": 1, "items": []}, {"day": 2, "items": []}]
    out = attach_hotels(dps, [{"day": 1, "hotel": {"name": "H1"}}])
    assert out[0]["hotel"] == {"name": "H1"}
    assert "hotel" not in out[1] or out[1].get("hotel") is None
    # 不改原对象
    assert "hotel" not in dps[0]


def test_hotel_keyword_maps_level():
    assert hotel_keyword("经济") == "经济型酒店"
    assert hotel_keyword("未知档") == "酒店"
