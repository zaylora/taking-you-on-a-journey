"""dispatch 节点：把当前消息 + 澄清 + 历史偏好标准化为结构化需求。"""
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage

from app.llm.factory import build_llm

_SYS = (
    "把用户的旅行需求整理为结构化字段。缺失项用合理默认：days 默认 3、num_people 默认 1、"
    "budget 默认 0（表示未指定）、start_date 缺失留空字符串。preferences 用键值对概括偏好。"
    "综合当前用户消息、会话摘要、最近消息和已澄清答案；用户没有重提的偏好可继承，"
    "用户明确修改的字段以最新消息为准。"
)


class NormalizedReq(BaseModel):
    city: str = Field(default="", description="目的地城市名，如“北京”“成都”；无法判断时留空字符串")
    start_date: str = Field(default="", description="出发日期，格式 YYYY-MM-DD；未指定时留空字符串")
    days: int = Field(default=3, description="行程天数，正整数；未指定时默认 3")
    num_people: int = Field(default=1, description="出行人数，正整数；未指定时默认 1")
    preferences: dict = Field(
        default_factory=dict,
        description=(
            "旅行偏好的键值对，键为偏好维度、值为对应取值，例如 "
            '{"风格": "美食", "节奏": "轻松", "住宿": "经济型"}；无偏好时返回空对象 {}'
        ),
    )
    budget: float = Field(default=0.0, description="总预算，单位人民币元；未指定时填 0 表示不限")


async def dispatch(state, config: RunnableConfig) -> dict:
    llm = build_llm(temperature=0).with_structured_output(NormalizedReq, method="function_calling")
    history = state.get("clarify_history", [])
    answered = "；".join(f"{h['field']}={h.get('answer','')}" for h in history) or "（无）"
    memory = state.get("memory_context", {}) or {}
    req = await llm.ainvoke([
        SystemMessage(content=_SYS),
        HumanMessage(content=str({
            "当前用户消息": state.get("query", ""),
            "会话摘要": state.get("conversation_summary", ""),
            "最近消息": memory.get("recent_messages", []),
            "当前结构化需求": state.get("normalized_req", {}) or {},
            "已澄清": answered,
        })),
    ], config=config)
    data = req.model_dump()
    return {
        **data,
        "normalized_req": data,
    }
