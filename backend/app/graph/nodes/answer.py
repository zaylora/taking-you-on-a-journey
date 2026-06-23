"""M5 QA node: answer using existing conversation and plan without modifying plan state."""
from langchain_core.runnables import RunnableConfig

from app.llm.factory import build_llm


_SYS = ("你是旅行助手。只基于当前会话摘要和已有行程回答用户问题，不要重新规划或修改 day_plans。"
        "若用户问及某景点为何未安排，可参考 dropped_attractions（含未排入景点及原因）说明。")


async def answer(state: dict, config: RunnableConfig) -> dict:
    clar = state.get("refine_clarification")
    if clar:
        return {"summary": clar, "changed_days": []}
    payload = {
        "question": state.get("query", ""),
        "conversation_summary": state.get("conversation_summary", ""),
        "day_plans": state.get("day_plans", []) or [],
        "budget": state.get("budget_check", {}) or {},
        "dropped_attractions": state.get("dropped_attractions", []) or [],
    }
    result = await build_llm(temperature=0).ainvoke(
        [{"role": "system", "content": _SYS}, {"role": "user", "content": str(payload)}],
        config=config,
    )
    content = result.content if hasattr(result, "content") else str(result)
    return {"summary": content, "changed_days": []}
