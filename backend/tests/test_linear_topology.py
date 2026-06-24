"""线性拓扑测试：验证切图后为 6 节点 0 条件边直线。

get_graph() 返回 langchain_core.runnables.graph.Graph：
  - .nodes: dict[str, Node]，key 为节点 id（含 __start__ / __end__）
  - .edges: list[Edge]，每条边有 .source / .target / .conditional
"""
from app.graph.builder import build_graph

EXPECTED_NODES = {"memory", "understand", "collect_context", "apply", "render", "memory_update"}

GONE_NODES = {
    "dispatch_agent", "clarify", "retrieve", "weather", "attractions",
    "restaurants", "transport", "enrich_duration", "itinerary",
    "accommodation", "budget", "refine", "answer", "summarize",
    "reset_plan_new",
}

# 期望的有序边链（不含 START/END 边，但一并验证）
EXPECTED_EDGE_CHAIN = [
    ("__start__", "memory"),
    ("memory", "understand"),
    ("understand", "collect_context"),
    ("collect_context", "apply"),
    ("apply", "render"),
    ("render", "memory_update"),
    ("memory_update", "__end__"),
]


def test_six_nodes_present():
    """6 个业务节点必须全部在图中。"""
    drawable = build_graph().get_graph()
    names = set(drawable.nodes.keys())
    for expected in EXPECTED_NODES:
        assert expected in names, f"节点 {expected!r} 不在图中，实际节点集: {names}"


def test_old_nodes_gone():
    """旧拓扑节点不得出现在新图中。"""
    drawable = build_graph().get_graph()
    names = set(drawable.nodes.keys())
    for gone in GONE_NODES:
        assert gone not in names, f"旧节点 {gone!r} 仍残留在图中，应已切除"


def test_no_conditional_edges():
    """0 条件边：所有 Edge.conditional 必须为 False。"""
    drawable = build_graph().get_graph()
    for edge in drawable.edges:
        assert not edge.conditional, (
            f"边 {edge.source!r} → {edge.target!r} 仍为条件边，应切为无条件"
        )


def test_linear_edge_chain():
    """验证完整的 START→memory→understand→collect_context→apply→render→memory_update→END 链。"""
    drawable = build_graph().get_graph()
    edge_pairs = {(e.source, e.target) for e in drawable.edges}
    for src, tgt in EXPECTED_EDGE_CHAIN:
        assert (src, tgt) in edge_pairs, (
            f"缺少边 {src!r} → {tgt!r}，实际边集: {sorted(edge_pairs)}"
        )


def test_total_node_count():
    """图中节点总数应为 6 业务节点 + __start__ + __end__ = 8。"""
    drawable = build_graph().get_graph()
    assert len(drawable.nodes) == 8, (
        f"期望 8 个节点（含 __start__/__end__），实际: {len(drawable.nodes)}，节点: {list(drawable.nodes.keys())}"
    )
