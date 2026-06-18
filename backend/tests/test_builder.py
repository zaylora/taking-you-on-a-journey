from app.graph.builder import build_graph


def test_graph_compiles_with_checkpointer():
    g = build_graph()
    assert g.checkpointer is not None  # MemorySaver 已挂


def test_graph_has_all_m2_nodes():
    g = build_graph()
    nodes = set(g.get_graph().nodes.keys())
    for n in ("clarify", "dispatch", "weather", "attractions",
              "restaurants", "transport", "itinerary", "summarize"):
        assert n in nodes
    # 占位节点不接线
    assert "accommodation" not in nodes and "budget" not in nodes
