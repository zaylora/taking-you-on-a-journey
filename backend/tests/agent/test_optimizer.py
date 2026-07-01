from app.tools.planning.routing.assembler import routes_to_day_plans
from app.tools.planning.routing.optimizer import solve_vrptw
from app.tools.planning.routing.prefilter import select_candidates


def _poi(name, lng, lat, rating=5.0):
    return {"name": name, "poi_id": name, "lng": lng, "lat": lat, "rating": rating}


def test_prefilter_caps_candidates():
    pois = [_poi(str(i), 104 + i * 0.01, 30.6) for i in range(20)]
    out = select_candidates(pois, days=2, per_day=4)
    assert len(out) <= 8


def test_solve_vrptw_distributes_across_days_no_empty():
    # 6 个点 + depot，2 天，应均衡分布、无空天
    nodes = [{"poi_id": "depot", "lng": 104.05, "lat": 30.65}]
    nodes += [_poi(str(i), 104.0 + i * 0.02, 30.6 + i * 0.02) for i in range(6)]
    import math
    n = len(nodes)
    mat = [[0.0 if i == j else (abs(i - j) * 600.0) for j in range(n)] for i in range(n)]
    routes = solve_vrptw(mat, days=2)
    assert len(routes) == 2
    visited = sorted(idx for r in routes for idx in r if idx != 0)
    assert visited == list(range(1, 7))  # 所有点都被访问一次
    assert all(len(r) > 0 for r in routes)  # 无空天


def test_routes_to_day_plans_builds_skeleton():
    candidates = [{"name": "A", "poi_id": "a", "lng": 104.0, "lat": 30.6},
                  {"name": "B", "poi_id": "b", "lng": 104.1, "lat": 30.7}]
    # routes 索引：0=depot，1->candidates[0]，2->candidates[1]
    routes = [[0, 1], [0, 2]]
    plans = routes_to_day_plans(routes, candidates)
    assert len(plans) == 2
    assert plans[0]["day"] == 1
    assert plans[0]["items"][0]["name"] == "A"
    assert plans[1]["items"][0]["name"] == "B"
