from app.itinerary.assembler import routes_to_skeleton


def _c(poi_id, lng, lat):
    return {"name": poi_id, "poi_id": poi_id, "lng": lng, "lat": lat, "visit_minutes": 60}


def _r(poi_id, lng, lat):
    return {"name": poi_id, "poi_id": poi_id, "lng": lng, "lat": lat}


def test_routes_to_skeleton_geometry_invariants():
    candidates = [_c("A", 113.0, 23.0), _c("B", 113.01, 23.0),
                  _c("C", 113.2, 23.1)]
    # 节点 index：1=A,2=B,3=C。第1天[1,2]，第2天[3]
    per_day = [[1, 2], [3]]
    rest_pools = [[_r("R1", 113.005, 23.0)], [_r("R2", 113.2, 23.1)]]
    skeleton, centers = routes_to_skeleton(per_day, candidates, rest_pools)
    assert len(skeleton) == 2
    assert len(centers) == 2
    for day in skeleton:
        items = day["items"]
        if items:
            assert items[0]["type"] != "transport"
            assert items[-1]["type"] != "transport"
        transports = [it for it in items if it["type"] == "transport"]
        stops = [it for it in items if it["type"] != "transport"]
        assert len(transports) == max(0, len(stops) - 1)


def test_empty_day_yields_empty_items():
    skeleton, centers = routes_to_skeleton([[], []], [], [[], []])
    assert all(day["items"] == [] for day in skeleton)
