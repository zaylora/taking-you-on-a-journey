"""M5 intent classification for true multiturn conversations."""
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.llm.factory import build_llm


class IntentResult(BaseModel):
    intent: Literal["plan_new", "refine_existing", "qa"]
    confidence: float = Field(default=1.0)
    reason: str = Field(default="")
    target_day: int | None = None
    needs_full_replan: bool = False


_SYS = (
    "判断用户本轮是在重新规划旅行、修改已有行程，还是只问答。"
    "已有 day_plans 时，提到刚才/第几天/换/删/加/改预算/改酒店/轻松一点通常是 refine_existing；"
    "只询问是否适合、为什么、建议说明是 qa；明确重新规划、换城市、重新做是 plan_new。"
)


_DAY_WORDS = {
    "一": 1, "1": 1, "二": 2, "2": 2, "两": 2, "三": 3, "3": 3,
    "四": 4, "4": 4, "五": 5, "5": 5, "六": 6, "6": 6, "七": 7, "7": 7,
}


def _target_day(text: str) -> int | None:
    for word, day in _DAY_WORDS.items():
        if f"第{word}天" in text or f"day {word}" in text.lower() or f"Day {word}" in text:
            return day
    return None


def _rule_based_intent(query: str, has_plan: bool) -> IntentResult | None:
    if not has_plan:
        return IntentResult(intent="plan_new", confidence=1.0, reason="当前没有可修改的行程")
    text = query.strip()
    if any(k in text for k in ("重新规划", "重新做", "重新安排", "换个城市", "新行程")):
        return IntentResult(intent="plan_new", confidence=0.95, reason="用户明确要求重新规划", needs_full_replan=True)
    day = _target_day(text)
    refine_keywords = ("太赶", "轻松", "少", "删", "删除", "换", "改", "预算", "酒店", "晚餐", "午餐", "加")
    if day is not None and any(k in text for k in refine_keywords):
        return IntentResult(intent="refine_existing", confidence=0.9, reason="用户引用已有行程局部修改", target_day=day)
    if any(k in text for k in ("适合", "吗", "为什么", "怎么", "离", "近吗", "建议")):
        return IntentResult(intent="qa", confidence=0.85, reason="用户询问当前方案")
    return None


async def intent(state: dict, config: RunnableConfig) -> dict:
    query = state.get("query", "")
    has_plan = bool(state.get("day_plans"))
    result = _rule_based_intent(query, has_plan)
    if result is None:
        llm = build_llm(temperature=0).with_structured_output(IntentResult, method="function_calling")
        result = await llm.ainvoke([
            SystemMessage(content=_SYS),
            HumanMessage(content=str({
                "query": query,
                "conversation_summary": state.get("conversation_summary", ""),
                "normalized_req": state.get("normalized_req", {}) or {},
                "has_day_plans": has_plan,
            })),
        ], config=config)
        if result.confidence < 0.55:
            result.intent = "qa"
    return {
        "last_intent": result.intent,
        "refine_request": {
            "target_day": result.target_day,
            "needs_full_replan": result.needs_full_replan,
            "reason": result.reason,
        },
    }


def route_after_intent(state: dict) -> str:
    intent_name = state.get("last_intent") or "plan_new"
    if intent_name == "refine_existing":
        return "refine"
    if intent_name == "qa":
        return "answer"
    return "plan_new"


def reset_for_plan_new(state: dict) -> dict:
    return {
        "clarified": False,
        "clarify_round": 0,
        "retry_count": 0,
        "day_plans": [],
        "budget_check": {},
        "daily_centers": [],
        "changed_days": [],
    }
