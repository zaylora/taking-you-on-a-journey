from app.itinerary.prefilter import select_candidates


def _a(poi_id, rating):
    return {"name": poi_id, "poi_id": poi_id, "rating": rating, "lng": 113.0, "lat": 23.0}


def test_keeps_all_when_under_cap():
    pts = [_a("a", 4.0), _a("b", 3.0)]
    cand, dropped = select_candidates(pts, days=3)
    assert len(cand) == 2
    assert dropped == []


def test_drops_lowest_rated_over_cap():
    # days=1 -> cap = 1*5*1.5 = 7(xiang xia qu zheng)
    pts = [_a(f"p{i}", float(i)) for i in range(9)]
    cand, dropped = select_candidates(pts, days=1)
    assert len(cand) == 7
    assert len(dropped) == 2
    # bei diao de shi ping fen zui di de p0,p1
    dropped_ids = {d["name"] for d in dropped}
    assert dropped_ids == {"p0", "p1"}
    assert all("reason" in d for d in dropped)


def test_deterministic_tie_break_by_poi_id():
    pts = [_a("b", 4.0), _a("a", 4.0), _a("c", 4.0)]
    cand, _ = select_candidates(pts, days=1)
    # tong fen an poi_id sheng xu bao liu shun xu que ding
    assert [c["poi_id"] for c in cand] == ["a", "b", "c"]
