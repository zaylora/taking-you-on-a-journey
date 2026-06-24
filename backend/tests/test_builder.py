"""构建器测试：验证 build_graph / make_graph 生成正确的 6 节点 0 条件边线性图。

Task 11 重写：切图为 START→memory→understand→collect_context→apply→render→memory_update→END。
旧拓扑断言（17 节点/条件边/dispatch/clarify 等）已删除，由 test_linear_topology.py 覆盖完整链断言。
"""
from app.graph.builder import build_graph, make_graph

EXPECTED_NODES = {"memory", "understand", "collect_context", "apply", "render", "memory_update"}


def test_graph_compiles_with_checkpointer():
    """build_graph() 默认挂载 MemorySaver。"""
    g = build_graph()
    assert g.checkpointer is not None


def test_make_graph_compiles_without_checkpointer():
    """make_graph() 不挂 checkpointer（由平台自动注入）。"""
    g = make_graph()
    assert g.checkpointer is None


def test_graph_has_six_linear_nodes():
    """图中包含且仅包含 6 个业务节点（加 __start__/__end__ 共 8 个）。"""
    g = build_graph()
    gg = g.get_graph()
    names = set(gg.nodes.keys())
    for n in EXPECTED_NODES:
        assert n in names, f"缺少节点 {n!r}"
    assert len(gg.nodes) == 8, f"期望 8 个节点，实际 {len(gg.nodes)}: {list(gg.nodes.keys())}"


def test_no_conditional_edges():
    """0 条件边：切图后不应存在任何条件路由。"""
    g = build_graph()
    gg = g.get_graph()
    for edge in gg.edges:
        assert not edge.conditional, f"边 {edge.source!r}→{edge.target!r} 仍为条件边"


def test_linear_edge_chain():
    """验证 START→memory→understand→collect_context→apply→render→memory_update→END 完整链。"""
    g = build_graph()
    gg = g.get_graph()
    edge_pairs = {(e.source, e.target) for e in gg.edges}
    expected_chain = [
        ("__start__", "memory"),
        ("memory", "understand"),
        ("understand", "collect_context"),
        ("collect_context", "apply"),
        ("apply", "render"),
        ("render", "memory_update"),
        ("memory_update", "__end__"),
    ]
    for src, tgt in expected_chain:
        assert (src, tgt) in edge_pairs, f"缺少边 {src!r}→{tgt!r}，实际边: {sorted(edge_pairs)}"
