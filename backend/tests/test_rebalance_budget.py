from app.graph.nodes.itinerary import rebalance_by_budget


def _a(name, rating, vm, lng=113.0, lat=23.0):
    return {"name": name, "poi_id": name, "rating": rating,
            "visit_minutes": vm, "lng": lng, "lat": lat}


def _bucket_minutes(bucket):
    return sum(a["visit_minutes"] + 40 for a in bucket)


def test_overloaded_day_sheds_lowest_rating():
    # 一天塞 4 个 *160min=640 > 480；另一天空 → 应迁移而非全丢
    day1 = [_a(f"p{i}", 4.0 + i * 0.1, 120) for i in range(4)]
    day2 = []
    balanced, dropped = rebalance_by_budget([day1, day2], day_budget=480)
    assert all(_bucket_minutes(b) <= 480 for b in balanced)
    # 4 个 160min 总 640，可分布到两天（每天≤3个=480），应迁移而非丢弃
    kept = sum(len(b) for b in balanced)
    assert kept == 4
    assert dropped == []


def test_drops_when_no_room_anywhere():
    # 单天，5 个 160min，预算 480 → 最多 3 个，丢 2 个
    day1 = [_a(f"p{i}", 4.0 + i * 0.05, 120) for i in range(5)]
    balanced, dropped = rebalance_by_budget([day1], day_budget=480)
    assert _bucket_minutes(balanced[0]) <= 480
    assert len(dropped) == 2
    assert all("reason" in d for d in dropped)


def test_within_budget_unchanged():
    day1 = [_a("a", 4.0, 120), _a("b", 4.0, 120)]
    balanced, dropped = rebalance_by_budget([day1], day_budget=480)
    assert len(balanced[0]) == 2
    assert dropped == []
