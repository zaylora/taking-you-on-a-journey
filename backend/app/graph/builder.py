"""图构建（M2）：clarify(interrupt 自循环) → dispatch → 4 并行检索 → itinerary → summarize。
compile(checkpointer=MemorySaver())：带 thread_id，interrupt 跨请求恢复。
"""
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.graph.state import TripState
from app.graph.nodes.clarify import clarify, route_after_clarify
from app.graph.nodes.dispatch import dispatch
from app.graph.nodes.weather import weather
from app.graph.nodes.attractions import attractions
from app.graph.nodes.restaurants import restaurants
from app.graph.nodes.transport import transport
from app.graph.nodes.itinerary import itinerary
from app.graph.nodes.summarize import summarize


def build_graph():
    g = StateGraph(TripState)
    for name, fn in [
        ("clarify", clarify), ("dispatch", dispatch),
        ("weather", weather), ("attractions", attractions),
        ("restaurants", restaurants), ("transport", transport),
        ("itinerary", itinerary), ("summarize", summarize),
    ]:
        g.add_node(name, fn)

    g.add_edge(START, "clarify")
    g.add_conditional_edges("clarify", route_after_clarify,
                            {"clarify": "clarify", "dispatch": "dispatch"})
    for n in ("weather", "attractions", "restaurants", "transport"):
        g.add_edge("dispatch", n)
        g.add_edge(n, "itinerary")
    g.add_edge("itinerary", "summarize")
    g.add_edge("summarize", END)
    return g.compile(checkpointer=MemorySaver())
