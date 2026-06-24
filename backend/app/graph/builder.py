"""图构建（线性化）：START → memory → understand → collect_context → apply → render → memory_update → END。

6 节点 0 条件边：从左读到右即执行顺序。understand 内用 interrupt 做需求澄清/可行性反问；
collect_context 按 operations 类型并发取数；apply 执行 operations 并重算住宿/预算；render 出话。
"""
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.graph.state import TripState
from app.graph.nodes.memory import memory
from app.graph.nodes.understand import understand
from app.graph.nodes.collect_context import collect_context_node
from app.graph.nodes.apply_node import apply_node
from app.graph.nodes.render import render
from app.graph.nodes.memory_update import memory_update


def _build_state_graph():
    g = StateGraph(TripState)
    for name, fn in [
        ("memory", memory),
        ("understand", understand),
        ("collect_context", collect_context_node),
        ("apply", apply_node),
        ("render", render),
        ("memory_update", memory_update),
    ]:
        g.add_node(name, fn)
    g.add_edge(START, "memory")
    g.add_edge("memory", "understand")
    g.add_edge("understand", "collect_context")
    g.add_edge("collect_context", "apply")
    g.add_edge("apply", "render")
    g.add_edge("render", "memory_update")
    g.add_edge("memory_update", END)
    return g


def build_graph(checkpointer=None):
    """本地 / 测试入口：默认用 MemorySaver。"""
    return _build_state_graph().compile(checkpointer=checkpointer or MemorySaver())


def make_graph():
    """LangGraph API/Platform 入口：不传 checkpointer，由平台自动注入持久化。"""
    return _build_state_graph().compile()
