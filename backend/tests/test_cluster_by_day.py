from app.graph.nodes.itinerary import cluster_by_day


def _pt(name, lng, lat): return {"name": name, "lng": lng, "lat": lat}


def test_returns_exactly_days_buckets():
    pts = [_pt(f"p{i}", 104.0 + i * 0.01, 30.6 + i * 0.01) for i in range(9)]
    res = cluster_by_day(pts, 3)
    assert len(res) == 3
    assert sum(len(b) for b in res) == 9


def test_balanced_counts():
    pts = [_pt(f"p{i}", 104.0 + i * 0.01, 30.6) for i in range(10)]
    counts = sorted(len(b) for b in cluster_by_day(pts, 3))
    assert counts[-1] - counts[0] <= 1  # 最多差 1，均衡


def test_empty_points():
    assert cluster_by_day([], 3) == [[], [], []]


def test_fewer_points_than_days():
    res = cluster_by_day([_pt("a", 104.0, 30.6)], 3)
    assert len(res) == 3 and sum(len(b) for b in res) == 1


def test_days_non_positive_treated_as_one():
    res = cluster_by_day([_pt("a", 104.0, 30.6), _pt("b", 104.1, 30.7)], 0)
    assert len(res) == 1 and len(res[0]) == 2


def test_intra_cluster_nearest_neighbor_order():
    # 一条直线上的点应按顺序串起来（首点固定后逐个最近邻）
    pts = [_pt("a", 104.00, 30.6), _pt("c", 104.20, 30.6), _pt("b", 104.10, 30.6)]
    res = cluster_by_day(pts, 1)[0]
    xs = [p["lng"] for p in res]
    assert xs == sorted(xs) or xs == sorted(xs, reverse=True)
