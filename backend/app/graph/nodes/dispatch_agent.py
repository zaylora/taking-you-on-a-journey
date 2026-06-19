"""dispatch_agent 节点（M5 fix）：单一前置派发 Agent。

合并原 intent（判意图）+ dispatch（plan_new 标准化）。三类意图：
- plan_new：规则/LLM 判定后，用 NormalizedReq 标准化需求并写顶层字段。
- refine_existing：用规则解析出结构化 RefineRequest（op/target_day/constraints/标志），不调 LLM。
- qa：只写 last_intent，交给 answer 节点。
clarify 在本节点之后、仅 plan_new 经过；clarify 自己把澄清答案并回 normalized_req。
"""
import re
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.graph.nodes.dispatch import NormalizedReq, _SYS as _DISPATCH_SYS

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


def _refine_flags(op: str) -> dict:
    """op -> 是否需补检索 / 是否需重算预算。确定性映射（见计划 Global Constraints 表）。"""
    needs_search = op in ("change_meal", "add", "replace")
    needs_budget_recheck = op != "reorder"
    return {"needs_search": needs_search, "needs_budget_recheck": needs_budget_recheck}


def _infer_op(query: str) -> str:
    if "预算" in query:
        return "change_budget"
    if "酒店" in query or "住宿" in query:
        return "change_hotel"
    if any(k in query for k in ("晚餐", "午餐", "餐厅", "吃", "饭")) and "换" in query:
        return "change_meal"
    if any(k in query for k in ("少", "删", "太赶", "轻松")):
        return "relax"
    if "换" in query:
        return "replace"
    if "加" in query:
        return "add"
    return "reorder"


def _parse_refine(query: str, target_day: int | None) -> dict:
    """纯规则把自然语言修改解析成结构化 RefineRequest dict。不调 LLM。"""
    op = _infer_op(query)
    constraints: dict = {}
    # "换成X"/"改成X" 的 X 作为检索关键词或目标项
    m = re.search(r"(?:换成|改成|换个|改为)\s*([一-龥A-Za-z0-9]{1,12})", query)
    if m:
        constraints["keywords"] = m.group(1)
    if op == "change_budget":
        num = re.search(r"(\d{3,6})", query)
        if num:
            constraints["budget"] = float(num.group(1))
    flags = _refine_flags(op)
    return {
        "op": op,
        "target_day": target_day,
        "target_item_name": constraints.get("keywords", "") if op in ("replace", "change_meal") else "",
        "constraints": constraints,
        "needs_search": flags["needs_search"],
        "needs_budget_recheck": flags["needs_budget_recheck"],
    }


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
        return {
            "last_intent": "refine_existing",
            "refine_request": _parse_refine(query, result.target_day),
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
