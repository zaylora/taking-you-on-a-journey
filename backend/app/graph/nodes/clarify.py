"""clarify 节点：interrupt 多轮需求澄清。
- LLM structured output 评估 (query + clarify_history) 找缺口。
- 无缺口 / 轮次到顶 → clarified=True 放行。
- 有缺口 → interrupt 抛出 {field,question,options}，resume 后写回 clarify_history。
⚠️ interrupt 前的评估在 resume 时会重跑，故 temperature=0 保持确定性。
"""
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from app.core.constants import MAX_CLARIFY_ROUNDS
from app.llm.factory import build_llm

_SYS = (
    "你是旅行需求澄清助手。判断用户需求中仍缺失、影响行程规划的关键要素"
    "（如城市、天数、人数、出发日期、预算档位、偏好）。只针对真正缺失的要素提问，"
    "每个缺口给一个简短中文问题；若是档位/单选类给 options，开放式问题 options 为空数组。"
    "若信息已足够规划，返回空 gaps。"
)


class Gap(BaseModel):
    field: str = Field(description="缺失要素字段名，如 city/days/budget")
    question: str = Field(description="向用户提出的简短中文问题")
    options: list[str] = Field(default_factory=list, description="可选项；开放式问题为空")


class ClarifyGaps(BaseModel):
    gaps: list[Gap] = Field(
        default_factory=list,
        description="仍需向用户澄清的缺失要素列表；信息已足够规划时返回空数组",
    )


async def _evaluate_gaps(state, config: RunnableConfig) -> list[Gap]:
    llm = build_llm(temperature=0).with_structured_output(ClarifyGaps, method="function_calling")
    history = state.get("clarify_history", [])
    answered = "；".join(f"{h['field']}={h.get('answer','')}" for h in history) or "（无）"
    prompt = [
        SystemMessage(content=_SYS),
        HumanMessage(content=f"原始需求：{state.get('query','')}\n已澄清：{answered}"),
    ]
    result = await llm.ainvoke(prompt, config=config)
    return result.gaps


async def clarify(state, config: RunnableConfig) -> dict:
    rnd = state.get("clarify_round", 0)
    if rnd >= MAX_CLARIFY_ROUNDS:
        return {"clarified": True}
    gaps = await _evaluate_gaps(state, config)
    if not gaps:
        return {"clarified": True}
    g = gaps[0]
    payload = {"field": g.field, "question": g.question, "options": g.options}
    answer = interrupt(payload)  # 暂停；resume 后 answer = Command(resume=...) 的值
    return {
        "clarify_history": [{**payload, "answer": answer}],
        "clarify_round": rnd + 1,
        "clarified": False,
    }


def route_after_clarify(state) -> str:
    return "dispatch" if state.get("clarified") else "clarify"
