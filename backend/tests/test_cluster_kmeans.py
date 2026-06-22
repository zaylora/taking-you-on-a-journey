from app.graph.nodes.itinerary import cluster_kmeans


def _pt(name, lng, lat):
    return {"name": name, "poi_id": name, "lng": lng, "lat": lat}


def test_returns_exactly_days_buckets():
    pts = [_pt(f"p{i}", 113.0 + i * 0.01, 23.0) for i in range(9)]
    res = cluster_kmeans(pts, 3)
    assert len(res) == 3
    assert sum(len(b) for b in res) == 9


def test_geographic_compactness():
    # 两簇明显分离：东边一团、西边一团 → 同簇应聚在一起
    west = [_pt(f"w{i}", 113.0 + i * 0.001, 23.0) for i in range(4)]
    east = [_pt(f"e{i}", 114.0 + i * 0.001, 23.0) for i in range(4)]
    res = cluster_kmeans(west + east, 2)
    # 每个桶应是纯西或纯东（不混）
    for bucket in res:
        prefixes = {p["name"][0] for p in bucket}
        assert len(prefixes) == 1


def test_fewer_points_than_days_falls_back():
    res = cluster_kmeans([_pt("a", 113.0, 23.0)], 3)
    assert len(res) == 3
    assert sum(len(b) for b in res) == 1


def test_empty_points():
    assert cluster_kmeans([], 3) == [[], [], []]
