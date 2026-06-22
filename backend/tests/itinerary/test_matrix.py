import pytest

from app.itinerary import matrix as M


def _n(poi_id, lng, lat):
    return {"poi_id": poi_id, "lng": lng, "lat": lat}


@pytest.mark.asyncio
async def test_matrix_uses_amap_and_caches(tmp_path, monkeypatch):
    db = str(tmp_path / "c.sqlite")
    nodes = [_n("A", 113.0, 23.0), _n("B", 113.1, 23.0)]
    calls = []

    async def fake_batch(origins, dest):
        calls.append((origins, dest))
        return [600.0 for _ in origins]  # 600 秒 = 10 分钟

    monkeypatch.setattr(M.amap, "distance_batch", fake_batch)
    mat = await M.distance_matrix(nodes, db)
    assert mat[0][0] == 0.0 and mat[1][1] == 0.0
    assert mat[0][1] == pytest.approx(10.0)
    # 第二次：命中缓存，不再调高德
    calls.clear()
    mat2 = await M.distance_matrix(nodes, db)
    assert mat2[0][1] == pytest.approx(10.0)
    assert calls == []


@pytest.mark.asyncio
async def test_matrix_falls_back_to_haversine_on_failure(tmp_path, monkeypatch):
    db = str(tmp_path / "c.sqlite")
    nodes = [_n("A", 113.0, 23.0), _n("B", 113.5, 23.0)]

    async def fail_batch(origins, dest):
        return [None for _ in origins]  # 高德失败

    monkeypatch.setattr(M.amap, "distance_batch", fail_batch)
    mat = await M.distance_matrix(nodes, db)
    # 降级 haversine：A-B 直线约 51km / 30kmh ~= 102 分钟，必为正数
    assert mat[0][1] > 0
