"""understand 单元节点（线性图 1/4）：dispatch_agent + clarify + preflight 三合一。

职责：
1. 判意图（复用 dispatch_agent._rule_based_intent + LLM 兜底）。
2. 解析 operations：plan_new→replace_plan；refine→ops（LLM）；qa→answer_only。
3. plan_new 需求澄清：节点内 while + interrupt 多轮（复用 clarify._evaluate_gaps/_apply_answer）。
4. preflight 闸门：补救可补字段（city/days）；可由用户补的缺口 → 单次 interrupt 反问。

⚠️ interrupt 前的所有 LLM 评估在 resume 时会重跑，必须 temperature=0 保持确定性（同 clarify）。
"""
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt

from app.core.constants import MAX_CLARIFY_ROUNDS
from app.graph.nodes.dispatch import NormalizedReq, _SYS as _DISPATCH_SYS
from app.graph.nodes.dispatch_agent import (
    IntentResult, _rule_based_intent, _INTENT_SYS,
    _REFINE_SYS, _day_plans_digest,
)
from app.graph.nodes.refine_ops import RefinePlan
from app.graph.nodes.clarify import _evaluate_gaps, _apply_answer
from app.planning.preflight import preflight
from app.llm.factory import build_llm


async def _llm_intent(state: dict, query: str, config) -> IntentResult:
    llm = build_llm(temperature=0).with_structured_output(IntentResult, method="function_calling")
    result = await llm.ainvoke([
        SystemMessage(content=_INTENT_SYS),
        HumanMessage(content=str({
            "query": query,
            "conversation_summary": state.get("conversation_summary", ""),
            "normalized_req": state.get("normalized_req", {}) or {},
            "has_day_plans": bool(state.get("day_plans")),
        })),
    ], config=config)
    if result.confidence < 0.55:
        result.intent = "qa"
    return result


async def _normalize_req(state: dict, query: str, config) -> dict:
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
    return req.model_dump()


async def understand(state: dict, config=None) -> dict:
    query = state.get("query", "")
    has_plan = bool(state.get("day_plans"))
    result = _rule_based_intent(query, has_plan) or await _llm_intent(state, query, config)

    # —— qa ——
    if result.intent == "qa":
        return {"operations": [{"op": "answer_only", "question": query}], "last_intent": "qa"}

    # —— refine ——
    if result.intent == "refine_existing":
        llm_refine = build_llm(temperature=0).with_structured_output(RefinePlan, method="function_calling")
        plan: RefinePlan = await llm_refine.ainvoke([
            SystemMessage(content=_REFINE_SYS),
            HumanMessage(content=str({
                "query": query,
                "target_day_hint": result.target_day,
                "day_plans": _day_plans_digest(state.get("day_plans") or []),
                "city": state.get("city", ""),
                "conversation_summary": state.get("conversation_summary", ""),
            })),
        ], config=config)
        if not plan.operations and plan.clarification:
            return {"operations": [{"op": "answer_only", "question": query}],
                    "last_intent": "qa", "refine_clarification": plan.clarification}
        operations = [o.model_dump() for o in plan.operations]
        req = dict(state.get("normalized_req", {}) or {})
        res = preflight(operations, {**state, "normalized_req": req})
        if res.clarification:
            ans = interrupt({"field": "city", "question": res.clarification, "options": []})
            req["city"] = ans.strip() if isinstance(ans, str) else req.get("city", "")
            res = preflight(operations, {**state, "normalized_req": req})
        return {"operations": res.operations, "last_intent": "refine_existing", "normalized_req": req}

    # —— plan_new ——
    norm = await _normalize_req(state, query, config)
    req = {**(state.get("normalized_req", {}) or {}), **norm}
    history: list[dict] = list(state.get("clarify_history", []) or [])
    rnd = 0
    while rnd < MAX_CLARIFY_ROUNDS:
        gaps = await _evaluate_gaps({**state, "query": query, "clarify_history": history}, config)
        if not gaps:
            break
        g = gaps[0]
        ans = interrupt({"field": g.field, "question": g.question, "options": g.options})
        patch = _apply_answer(g.field, ans, {"normalized_req": req})
        req = patch["normalized_req"]
        history.append({"field": g.field, "question": g.question, "options": g.options, "answer": ans})
        rnd += 1

    operations = [{"op": "replace_plan", "requirements_patch": req}]
    res = preflight(operations, {**state, "normalized_req": req})
    top = {k: req[k] for k in ("city", "start_date", "days", "num_people", "budget") if k in req}
    return {"operations": res.operations, "last_intent": "plan_new",
            "normalized_req": req, "clarified": True, **top}
