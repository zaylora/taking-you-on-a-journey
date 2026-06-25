from app.graph.builder import build_graph
from app.graph.nodes.clarify import _apply_answer


def test_apply_answer_maps_known_fields():
    assert _apply_answer("city", "成都", {})["city"] == "成都"
    out = _apply_answer("days", "3", {})
    assert out["days"] == 3 and out["normalized_req"]["days"] == 3
    out2 = _apply_answer("budget", "4000", {})
    assert out2["budget"] == 4000.0
    # 未知字段并入 preferences
    out3 = _apply_answer("风格", "美食", {"preferences": {}})
    assert out3["preferences"]["风格"] == "美食"
