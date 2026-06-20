from app.graph.builder import build_graph


def test_graph_compiles_with_checkpointer():
    g = build_graph()
    assert g.checkpointer is not None  # MemorySaver 已挂


def test_graph_has_all_core_nodes():
    g = build_graph()
    nodes = set(g.get_graph().nodes.keys())
    for n in ("clarify", "dispatch_agent", "retrieve", "weather", "attractions",
              "restaurants", "transport", "itinerary", "summarize"):
        assert n in nodes


def test_graph_has_m5fix_conditional_chain():
    g = build_graph()
    gg = g.get_graph()
    nodes = set(gg.nodes.keys())
    assert "accommodation" in nodes and "budget" in nodes
    edges = {(e.source, e.target) for e in gg.edges}
    # itinerary 与 refine 都条件分流到 accommodation/budget/summarize
    for src in ("itinerary", "refine"):
        assert {(src, "accommodation"), (src, "budget"), (src, "summarize")} <= edges
    # accommodation 条件分流到 budget/summarize
    assert {("accommodation", "budget"), ("accommodation", "summarize")} <= edges
    # budget 超支回退仍可达 itinerary
    assert ("budget", "itinerary") in edges
