from app.agent.planning import cluster_by_day, daily_centers_of, DayPlans, PlanItem


def _p(name, lng, lat):
    return {"name": name, "lng": lng, "lat": lat}


def test_cluster_empty_returns_empty_buckets():
    assert cluster_by_day([], 3) == [[], [], []]


def test_cluster_balances_points_across_days():
    pts = [_p(str(i), 104.0 + i * 0.01, 30.6 + i * 0.01) for i in range(6)]
    buckets = cluster_by_day(pts, 3)
    assert len(buckets) == 3
    assert sum(len(b) for b in buckets) == 6
    # 均衡：每天 2 个
    assert all(len(b) == 2 for b in buckets)


def test_daily_centers_centroid():
    clusters = [[_p("a", 100.0, 30.0), _p("b", 102.0, 32.0)], []]
    centers = daily_centers_of(clusters)
    assert centers[0] == {"lng": 101.0, "lat": 31.0}
    assert centers[1] == {"lng": 0.0, "lat": 0.0}


def test_dayplans_schema_parses():
    dp = DayPlans(days=[{"day": 1, "items": [{"type": "attraction", "name": "故宫"}]}])
    assert dp.days[0].day == 1
    assert dp.days[0].items[0].name == "故宫"
