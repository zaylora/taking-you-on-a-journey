"""图构建：memory → dispatch_agent →（clarify→retrieve→检索）/refine/answer → 按需重排 → summarize → memory_update。"""
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.graph.state import TripState
from app.graph.nodes.memory import memory
from app.graph.nodes.dispatch_agent import dispatch_agent, reset_for_plan_new, route_after_dispatch
from app.graph.nodes.clarify import clarify, route_after_clarify
from app.graph.nodes.retrieve import retrieve
from app.graph.nodes.weather import weather
from app.graph.nodes.attractions import attractions
from app.graph.nodes.enrich_duration import enrich_duration
from app.graph.nodes.restaurants import restaurants
from app.graph.nodes.transport import transport
from app.graph.nodes.itinerary import itinerary
from app.graph.nodes.accommodation import accommodation
from app.graph.nodes.budget import budget, route_after_budget
from app.graph.nodes.routing import route_after_plan, route_after_accommodation
from app.graph.nodes.summarize import summarize
from app.graph.nodes.refine import refine
from app.graph.nodes.answer import answer
from app.graph.nodes.memory_update import memory_update


def reset_plan_new(state):
    return reset_for_plan_new(state)


def _build_state_graph():
    g = StateGraph(TripState)
    for name, fn in [
        ("memory", memory), ("dispatch_agent", dispatch_agent), ("reset_plan_new", reset_plan_new),
        ("clarify", clarify), ("retrieve", retrieve),
        ("weather", weather), ("attractions", attractions),
        ("restaurants", restaurants), ("transport", transport),
        ("enrich_duration", enrich_duration),
        ("itinerary", itinerary), ("accommodation", accommodation),
        ("budget", budget), ("summarize", summarize),
        ("refine", refine), ("answer", answer), ("memory_update", memory_update),
    ]:
        g.add_node(name, fn)

    g.add_edge(START, "memory")
    g.add_edge("memory", "dispatch_agent")
    g.add_conditional_edges("dispatch_agent", route_after_dispatch,
                            {"plan_new": "reset_plan_new", "refine": "refine", "answer": "answer"})
    g.add_edge("reset_plan_new", "clarify")
    g.add_conditional_edges("clarify", route_after_clarify,
                            {"clarify": "clarify", "retrieve": "retrieve"})
    # 四路检索并行，统一 fan-in 到 enrich_duration（同深度屏障，避免 itinerary
    # 多深度入边在不同 superstep 重复触发→day_plans 重复写）。enrich_duration 仅
    # 读写 attractions 估游玩时长，其余三路 channel 原样透传；之后单边触发 itinerary。
    for n in ("weather", "attractions", "restaurants", "transport"):
        g.add_edge("retrieve", n)
        g.add_edge(n, "enrich_duration")
    g.add_edge("enrich_duration", "itinerary")
    g.add_conditional_edges("itinerary", route_after_plan,
                            {"accommodation": "accommodation", "budget": "budget", "summarize": "summarize"})
    g.add_conditional_edges("refine", route_after_plan,
                            {"accommodation": "accommodation", "budget": "budget", "summarize": "summarize"})
    g.add_conditional_edges("accommodation", route_after_accommodation,
                            {"budget": "budget", "summarize": "summarize"})
    g.add_conditional_edges("budget", route_after_budget,
                            {"itinerary": "itinerary", "summarize": "summarize"})
    g.add_edge("answer", "memory_update")
    g.add_edge("summarize", "memory_update")
    g.add_edge("memory_update", END)
    return g


def build_graph(checkpointer=None):
    """本地 / 测试入口：默认用 MemorySaver。"""
    return _build_state_graph().compile(checkpointer=checkpointer or MemorySaver())


def make_graph():
    """LangGraph API/Platform 入口：不传 checkpointer，由平台自动注入持久化。

    平台对单参数工厂会把 RunnableConfig(dict) 当 config 注入，故这里用零参数，
    且 compile 不带 checkpointer（否则与平台持久化层冲突）。
    """
    return _build_state_graph().compile()
