"""图构建：clarify → dispatch → retrieval → itinerary → accommodation → budget → summarize."""
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.graph.state import TripState
from app.graph.nodes.memory import memory
from app.graph.nodes.intent import intent, reset_for_plan_new, route_after_intent
from app.graph.nodes.clarify import clarify, route_after_clarify
from app.graph.nodes.dispatch import dispatch
from app.graph.nodes.weather import weather
from app.graph.nodes.attractions import attractions
from app.graph.nodes.restaurants import restaurants
from app.graph.nodes.transport import transport
from app.graph.nodes.itinerary import itinerary
from app.graph.nodes.accommodation import accommodation
from app.graph.nodes.budget import budget, route_after_budget
from app.graph.nodes.summarize import summarize
from app.graph.nodes.refine import refine
from app.graph.nodes.answer import answer
from app.graph.nodes.memory_update import memory_update


def reset_plan_new(state):
    return reset_for_plan_new(state)


def build_graph(checkpointer=None):
    g = StateGraph(TripState)
    for name, fn in [
        ("memory", memory), ("intent", intent), ("reset_plan_new", reset_plan_new),
        ("clarify", clarify), ("dispatch", dispatch),
        ("weather", weather), ("attractions", attractions),
        ("restaurants", restaurants), ("transport", transport),
        ("itinerary", itinerary), ("accommodation", accommodation),
        ("budget", budget), ("summarize", summarize),
        ("refine", refine), ("answer", answer), ("memory_update", memory_update),
    ]:
        g.add_node(name, fn)

    g.add_edge(START, "memory")
    g.add_edge("memory", "intent")
    g.add_conditional_edges("intent", route_after_intent,
                            {"plan_new": "reset_plan_new", "refine": "refine", "answer": "answer"})
    g.add_edge("reset_plan_new", "clarify")
    g.add_conditional_edges("clarify", route_after_clarify,
                            {"clarify": "clarify", "dispatch": "dispatch"})
    for n in ("weather", "attractions", "restaurants", "transport"):
        g.add_edge("dispatch", n)
        g.add_edge(n, "itinerary")
    g.add_edge("itinerary", "accommodation")
    g.add_edge("accommodation", "budget")
    g.add_conditional_edges("budget", route_after_budget,
                            {"itinerary": "itinerary", "summarize": "summarize"})
    g.add_edge("refine", "budget")
    g.add_edge("answer", "memory_update")
    g.add_edge("summarize", "memory_update")
    g.add_edge("memory_update", END)
    return g.compile(checkpointer=checkpointer or MemorySaver())
