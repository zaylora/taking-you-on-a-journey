"""M5 memory update: append lightweight chat history after each completed turn."""
from langchain_core.messages import AIMessage, HumanMessage


def _assistant_receipt(state: dict) -> str:
    intent = state.get("last_intent")
    if intent == "refine_existing":
        days = state.get("changed_days", []) or []
        if days:
            joined = "、".join(f"第{d}天" for d in days)
            return f"已根据你的要求调整{joined}，详见行程面板。"
        return "已尝试根据你的要求调整行程，详见行程面板。"
    if intent == "qa":
        return state.get("summary", "已回答你的问题。")
    req = state.get("normalized_req", {}) or {}
    city = req.get("city") or state.get("city") or "目的地"
    days = req.get("days") or state.get("days")
    if days:
        return f"已生成{city} {days}天行程，详见行程面板。"
    return f"已生成{city}行程，详见行程面板。"


def memory_update(state: dict) -> dict:
    return {
        "messages": [
            HumanMessage(content=state.get("query", "")),
            AIMessage(content=_assistant_receipt(state)),
        ]
    }
