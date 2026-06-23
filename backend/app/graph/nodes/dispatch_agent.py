"""dispatch_agent 节点（M5 fix）：单一前置派发 Agent。

合并原 intent（判意图）+ dispatch（plan_new 标准化）。三类意图：
- plan_new：规则/LLM 判定后，用 NormalizedReq 标准化需求并写顶层字段。
- refine_existing：调 LLM 结构化输出（RefinePlan）解析成可组合原子操作 operations；无法解析时产出 clarification 反问。
- qa：只写 last_intent，交给 answer 节点。
clarify 在本节点之后、仅 plan_new 经过；clarify 自己把澄清答案并回 normalized_req。
"""
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.graph.nodes.dispatch import NormalizedReq, _SYS as _DISPATCH_SYS
from app.graph.nodes.refine_ops import RefinePlan

from app.llm.factory import build_llm


class IntentResult(BaseModel):
    intent: Literal["plan_new", "refine_existing", "qa"]
    confidence: float = Field(default=1.0)
    reason: str = Field(default="")
    target_day: int | None = None
    needs_full_replan: bool = False


_INTENT_SYS = (
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
        if f"第{word}天" in text or f"day {word}" in text.lower():
            return day
    return None


def _rule_based_intent(query: str, has_plan: bool) -> IntentResult | None:
    if not has_plan:
        return IntentResult(intent="plan_new", confidence=1.0, reason="当前没有可修改的行程")
    text = query.strip()
    if any(k in text for k in ("重新规划", "重新做", "重新安排", "换个城市", "新行程")):
        return IntentResult(intent="plan_new", confidence=0.95, reason="用户明确要求重新规划", needs_full_replan=True)
    day = _target_day(text)
    refine_keywords = ("太赶", "轻松", "少", "删", "删除", "换", "改", "调整", "顺序",
                       "预算", "酒店", "住宿", "晚餐", "午餐", "加")
    if any(k in text for k in refine_keywords):
        return IntentResult(intent="refine_existing", confidence=0.9, reason="用户引用已有行程局部修改", target_day=day)
    if any(k in text for k in ("适合", "吗", "为什么", "怎么", "离", "近吗", "建议")):
        return IntentResult(intent="qa", confidence=0.85, reason="用户询问当前方案")
    return None


_REFINE_SYS = (
    "你是行程修改解析器。把用户对【已有行程】的修改诉求，解析成有序的原子操作列表。"
    "可用操作：set_region(换某天到新区域 area)、add_poi(加景点/餐 query+kind)、"
    "remove_poi(删项 selector)、replace_poi(换项 selector+query+kind)、"
    "reorder(调顺序 strategy)、set_pace(轻松/紧凑 direction)、set_budget(改预算 amount)、"
    "set_hotel(换酒店 criteria)。复合诉求拆成多个操作并按语序排列。"
    "day 必须依据所给 day_plans 判定（从 1 开始）。selector 可按 name 或 ordinal(kind+index,-1=最后)。"
    "若完全无法理解要改什么，operations 留空并在 clarification 用一句中文反问。"
)


def _day_plans_digest(day_plans: list) -> list:
    """压缩 day_plans 给 LLM 看结构（天号 + 各项类型与名称），不下发坐标等噪声。"""
    digest = []
    for d in day_plans or []:
        items = [{"type": it.get("type"), "name": it.get("name", "")}
                 for it in (d.get("items") or []) if it.get("type") != "transport"]
        digest.append({"day": d.get("day"), "items": items})
    return digest


async def _parse_refine_llm(state: dict, query: str, target_day, config) -> RefinePlan:
    llm = build_llm(temperature=0).with_structured_output(RefinePlan, method="function_calling")
    return await llm.ainvoke([
        SystemMessage(content=_REFINE_SYS),
        HumanMessage(content=str({
            "query": query,
            "target_day_hint": target_day,
            "day_plans": _day_plans_digest(state.get("day_plans") or []),
            "city": state.get("city", ""),
            "conversation_summary": state.get("conversation_summary", ""),
        })),
    ], config=config)


async def dispatch_agent(state: dict, config: RunnableConfig) -> dict:
    query = state.get("query", "")
    has_plan = bool(state.get("day_plans"))
    result = _rule_based_intent(query, has_plan)
    if result is None:
        llm = build_llm(temperature=0).with_structured_output(IntentResult, method="function_calling")
        result = await llm.ainvoke([
            SystemMessage(content=_INTENT_SYS),
            HumanMessage(content=str({
                "query": query,
                "conversation_summary": state.get("conversation_summary", ""),
                "normalized_req": state.get("normalized_req", {}) or {},
                "has_day_plans": has_plan,
            })),
        ], config=config)
        if result.confidence < 0.55:
            result.intent = "qa"

    if result.intent == "qa":
        return {"last_intent": "qa"}

    if result.intent == "refine_existing":
        plan = await _parse_refine_llm(state, query, result.target_day, config)
        if not plan.operations and plan.clarification:
            return {"last_intent": "qa", "refine_clarification": plan.clarification}
        return {
            "last_intent": "refine_existing",
            "refine_request": {
                "operations": [o.model_dump() for o in plan.operations],
                "clarification": plan.clarification,
            },
        }

    # plan_new：标准化需求（LLM），写顶层字段供检索消费
    llm = build_llm(temperature=0).with_structured_output(NormalizedReq, method="function_calling")
    memory = state.get("memory_context", {}) or {}
    req = await llm.ainvoke([
        SystemMessage(content=_DISPATCH_SYS),
        HumanMessage(content=str({
            "当前用户消息": query,
            "会话摘要": state.get("conversation_summary", ""),
            "最近消息": memory.get("recent_messages", []),
            "当前结构化需求": state.get("normalized_req", {}) or {},
        })),
    ], config=config)
    data = req.model_dump()
    return {"last_intent": "plan_new", **data, "normalized_req": data}


def route_after_dispatch(state: dict) -> str:
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
        "refine_request": {},
    }
