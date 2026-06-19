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


def test_graph_uses_dispatch_agent_not_intent_dispatch():
    nodes = set(build_graph().get_graph().nodes.keys())
    assert "dispatch_agent" in nodes and "retrieve" in nodes
    assert "intent" not in nodes and "dispatch" not in nodes


def test_graph_front_edges():
    gg = build_graph().get_graph()
    edges = {(e.source, e.target) for e in gg.edges}
    assert ("memory", "dispatch_agent") in edges
    assert ("reset_plan_new", "clarify") in edges
    for n in ("weather", "attractions", "restaurants", "transport"):
        assert ("retrieve", n) in edges
        assert (n, "itinerary") in edges
