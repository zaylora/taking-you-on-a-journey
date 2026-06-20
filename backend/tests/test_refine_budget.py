from app.graph.nodes.refine import _poi_to_item, _relax_until_budget


def test_poi_to_item_has_visit_minutes():
    poi = {"name": "博物馆", "poi_id": "B1", "lng": 113.0, "lat": 23.0,
           "type": "博物馆"}
    item = _poi_to_item(poi, "attraction")
    assert item["visit_minutes"] == 150  # 静态兜底


def test_relax_until_budget_removes_until_fit():
    # 当天 4 个景点各 160min = 640+ > 480 → relax 应删到不超预算
    items = [{"type": "attraction", "name": f"p{i}", "poi_id": f"p{i}",
              "visit_minutes": 120, "location": {"lng": 113.0 + i * 0.01, "lat": 23.0}}
             for i in range(4)]
    day = {"day": 1, "items": items}
    out = _relax_until_budget(day)
    from app.graph.nodes.time_budget import day_used_minutes, DAY_BUDGET
    assert day_used_minutes(out["items"]) <= DAY_BUDGET
    # out["items"] 含重派生的 transport 段，故只数停靠点
    stops = [it for it in out["items"] if it.get("type") != "transport"]
    assert len(stops) < 4
