"""dispatch 节点（M2 升级）：把 query + clarify_history 标准化为结构化需求。"""
from pydantic import BaseModel, Field

from app.llm.factory import build_llm

_SYS = (
    "把用户的旅行需求整理为结构化字段。缺失项用合理默认：days 默认 3、num_people 默认 1、"
    "budget 默认 0（表示未指定）、start_date 缺失留空字符串。preferences 用键值对概括偏好。"
)


class NormalizedReq(BaseModel):
    city: str = ""
    start_date: str = ""
    days: int = 3
    num_people: int = 1
    preferences: dict = Field(default_factory=dict)
    budget: float = 0.0


async def dispatch(state) -> dict:
    llm = build_llm(temperature=0).with_structured_output(NormalizedReq)
    history = state.get("clarify_history", [])
    answered = "；".join(f"{h['field']}={h.get('answer','')}" for h in history) or "（无）"
    req = await llm.ainvoke([
        {"role": "system", "content": _SYS},
        {"role": "user", "content": f"原始需求：{state.get('query','')}\n已澄清：{answered}"},
    ])
    data = req.model_dump()
    return {
        **data,
        "normalized_req": data,
        "messages": [{"role": "user", "content": state.get("query", "")}],
    }
