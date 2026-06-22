from app.graph.nodes.itinerary import select_by_rating


def _a(name, rating, vm, lng=113.0, lat=23.0):
    return {"name": name, "poi_id": name, "rating": rating,
            "visit_minutes": vm, "lng": lng, "lat": lat}


def test_keeps_high_rating_first():
    pts = [_a("low", 3.0, 120), _a("high", 4.8, 120), _a("mid", 4.0, 120)]
    selected, _ = select_by_rating(pts, days=1, day_budget=400)
    names = [p["name"] for p in selected]
    assert names[0] == "high"  # 最高分排最前


def test_drops_overflow_by_budget():
    # 每景点 120+40=160 分钟；1 天 400 分钟 → 最多 2 个
    pts = [_a(f"p{i}", 4.0 + i * 0.1, 120) for i in range(5)]
    selected, dropped = select_by_rating(pts, days=1, day_budget=400)
    assert len(selected) == 2
    assert len(dropped) == 3
    assert all("reason" in d for d in dropped)


def test_all_fit_when_budget_large():
    pts = [_a(f"p{i}", 4.0, 60) for i in range(3)]
    selected, dropped = select_by_rating(pts, days=2, day_budget=480)
    assert len(selected) == 3
    assert dropped == []
