from app.graph.nodes.apply_node import apply_node
from app.graph.nodes.itinerary import insert_transport


def _plan():
    day1 = [{"type": "attraction", "name": "A", "poi_id": "B1", "location": {"lng": 104.05, "lat": 30.65}},
            {"type": "meal", "name": "饭", "poi_id": "M1", "location": {"lng": 104.06, "lat": 30.66}}]
    return [{"day": 1, "items": insert_transport(day1), "center": {"lng": 104.055, "lat": 30.655}}]


async def test_apply_node_wraps_refine_notes():
    out = await apply_node(
        {"operations": [{"op": "reorder", "day": 1, "strategy": "reverse"}],
         "context": {}, "day_plans": _plan(), "plan_version": 1}, None)
    assert "refine_notes" in out
    assert out["refine_notes"]["applied"]
    assert "applied" not in out and "skipped" not in out   # 已收进 refine_notes
    assert out["changed_days"] == [1]


async def test_apply_node_answer_only_noop():
    out = await apply_node(
        {"operations": [{"op": "answer_only", "question": "为什么"}],
         "context": {}, "day_plans": _plan(), "plan_version": 1}, None)
    assert out["changed_days"] == [] and out["plan_version"] == 1
