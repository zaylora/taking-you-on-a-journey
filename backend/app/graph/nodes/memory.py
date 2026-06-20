"""M5 memory node: prepare lightweight context for this turn."""


RECENT_KEEP_MESSAGES = 8


def memory(state: dict) -> dict:
    messages = state.get("messages", []) or []
    recent = messages[-RECENT_KEEP_MESSAGES:]
    return {
        "memory_context": {
            "conversation_summary": state.get("conversation_summary", ""),
            "recent_messages": recent,
            "current_plan": state.get("day_plans", []) or [],
            "normalized_req": state.get("normalized_req", {}) or {},
        }
    }
