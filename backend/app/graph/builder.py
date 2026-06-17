"""图构建：START → dispatch → summarize → END。

方案 A：nodes/ 下全量铺设 10 个节点文件，但 M1 只把 dispatch / summarize 接线进图。
其余占位节点只建文件、不 add_edge，保证编译出的图永远可运行。
"""
from langgraph.graph import StateGraph, START, END

from app.graph.state import TripState
from app.graph.nodes.dispatch import dispatch
from app.graph.nodes.summarize import summarize


def build_graph():
    g = StateGraph(TripState)
    g.add_node("dispatch", dispatch)
    g.add_node("summarize", summarize)
    g.add_edge(START, "dispatch")
    g.add_edge("dispatch", "summarize")
    g.add_edge("summarize", END)
    return g.compile()  # M1：不传 checkpointer（单轮、无状态）
