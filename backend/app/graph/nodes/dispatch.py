"""dispatch 节点（M1 真实现）：把用户 query 塞入 messages。不调模型，保持同步。"""
from app.graph.state import TripState


def dispatch(state: TripState) -> dict:
    return {"messages": [{"role": "user", "content": state["query"]}]}
