import pytest

from app.tools.planning.routing import matrix


def test_haversine_seconds_zero_for_same_point():
    p = {"lng": 104.06, "lat": 30.65}
    assert matrix.haversine_seconds(p, p) == 0.0


def test_haversine_seconds_positive_for_distinct():
    a = {"lng": 104.06, "lat": 30.65}
    b = {"lng": 104.10, "lat": 30.70}
    assert matrix.haversine_seconds(a, b) == pytest.approx(809.8, abs=10)


@pytest.mark.asyncio
async def test_duration_matrix_haversine_fallback(tmp_path):
    nodes = [
        {"poi_id": "a", "lng": 104.0, "lat": 30.6},
        {"poi_id": "b", "lng": 104.1, "lat": 30.7},
    ]
    db = str(tmp_path / "dist.sqlite")
    m = await matrix.duration_matrix(nodes, db, use_amap=False)
    assert len(m) == 2 and len(m[0]) == 2
    assert m[0][0] == 0.0 and m[1][1] == 0.0
    assert m[0][1] == pytest.approx(1760.2, abs=10) and m[1][0] == pytest.approx(1760.2, abs=10)


@pytest.mark.asyncio
async def test_duration_matrix_uses_cache_second_call(tmp_path, monkeypatch):
    calls = {"n": 0}

    async def _fake_batch(origins, destination, type_="1"):
        calls["n"] += 1
        return [{"origin_id": i + 1, "dest_id": 1, "distance": 1000, "duration": 600}
                for i in range(len(origins))]

    monkeypatch.setattr("app.tools.clients.amap.distance_batch", _fake_batch)
    nodes = [{"poi_id": "a", "lng": 104.0, "lat": 30.6},
             {"poi_id": "b", "lng": 104.1, "lat": 30.7}]
    db = str(tmp_path / "dist.sqlite")
    await matrix.duration_matrix(nodes, db, use_amap=True)
    first = calls["n"]
    await matrix.duration_matrix(nodes, db, use_amap=True)  # 第二次应命中缓存
    assert calls["n"] == first  # 缓存命中，无新增 amap 调用
