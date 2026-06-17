"""summarize 节点（M1 真实现）：调 LLM 工厂流式生成。

⚠️ 必须 async + 接收 config + 用 astream(..., config=config) 显式透传：
Python ≤3.10 的 async 环境下 RunnableConfig 不经 contextvars 自动传播，
若用同步 .invoke() 或不透传 config，on_chat_model_stream 不会冒泡，前端收不到逐字 token。
（已用 astream_events 探针实测确认）
"""
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from app.graph.state import TripState
from app.llm.factory import build_llm


async def summarize(state: TripState, config: RunnableConfig) -> dict:
    parts: list[str] = []
    async for chunk in build_llm().astream(state["messages"], config=config):
        if chunk.content:
            parts.append(chunk.content)
    text = "".join(parts)
    return {"messages": [AIMessage(content=text)], "summary": text}
