from app.graph.builder import build_graph


def test_graph_compiles_with_checkpointer():
    g = build_graph()
    assert g.checkpointer is not None  # MemorySaver 已挂


def test_graph_has_all_core_nodes():
    g = build_graph()
    nodes = set(g.get_graph().nodes.keys())
    for n in ("clarify", "dispatch", "weather", "attractions",
              "restaurants", "transport", "itinerary", "summarize"):
        assert n in nodes


def test_graph_has_m4_accommodation_and_budget_edges():
    g = build_graph()
    gg = g.get_graph()
    nodes = set(gg.nodes.keys())
    assert "accommodation" in nodes and "budget" in nodes
    edges = {(e.source, e.target) for e in gg.edges}
    assert ("itinerary", "accommodation") in edges
    assert ("accommodation", "budget") in edges
    assert ("itinerary", "summarize") not in edges          # 旧直连已删
    budget_targets = {t for (s, t) in edges if s == "budget"}
    assert {"itinerary", "summarize"} <= budget_targets     # 超支条件边两个去向
