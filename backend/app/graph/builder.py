"""图构建：全局单 Agent ReAct。build_graph 直接返回 create_agent 组装的 agent。

历史上这里是 16 节点固定编排图；ReAct 重构后坍缩为单一 agent（见 app/agent/build.py）。
保留 build_graph(checkpointer) 签名，main.py 无需改动。
"""
from app.agent.build import build_trip_agent


def build_graph(checkpointer=None):
    return build_trip_agent(checkpointer)


def make_graph():
    """langgraph dev / LangGraph Platform 入口。

    平台自带持久化（checkpointer + store），显式传 None 关掉内置 MemorySaver，
    避免与平台冲突。langgraph.json 的 graphs 指向本函数。
    """
    return build_trip_agent(checkpointer=None)
