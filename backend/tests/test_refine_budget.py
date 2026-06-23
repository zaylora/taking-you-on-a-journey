from app.graph.nodes.refine import _poi_to_item, _relax_stops
from app.graph.nodes.time_budget import day_used_minutes, DAY_BUDGET
from app.graph.nodes.itinerary import insert_transport


def test_poi_to_item_has_visit_minutes():
    poi = {"name": "博物馆", "poi_id": "B1", "lng": 113.0, "lat": 23.0, "type": "博物馆"}
    item = _poi_to_item(poi, "attraction")
    assert item["visit_minutes"] == 150  # 静态兜底


def test_relax_stops_removes_until_fit():
    stops = [{"type": "attraction", "name": f"p{i}", "poi_id": f"p{i}",
              "visit_minutes": 120, "location": {"lng": 113.0 + i * 0.01, "lat": 23.0}}
             for i in range(4)]
    out = _relax_stops(stops)               # 返回停靠点列表（无交通段）
    assert day_used_minutes(insert_transport(out)) <= DAY_BUDGET
    assert len(out) < 4
