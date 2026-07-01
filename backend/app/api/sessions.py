"""M5 匿名对话会话接口。"""
from fastapi import APIRouter, HTTPException, Request, Response

from app.services.message_history import (
    aggregate_messages,
    extract_content,
    messages_with_xhs_sources,
    reconstruct_messages_from_graph_history,
    tool_steps,
)

router = APIRouter()


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _extract_content(message) -> str:
    return extract_content(message)


def _is_summarization_message(message) -> bool:
    return getattr(message, "additional_kwargs", {}).get("lc_source") == "summarization"


def _tool_steps(message) -> list[dict]:
    return tool_steps(message)


def _aggregate_messages(messages) -> list[dict]:
    """把 ReAct 一轮内的多个 AIMessage 聚合成单条 assistant 消息。

    单 Agent ReAct 一次回答会产生多个 AIMessage（每轮 model 决策一个，
    中间轮往往只有 tool_calls、正文为空，最后一轮才有正文）。历史快照若逐条
    渲染会得到多条空气泡，且与实时流「单条消息内聚合工具链」的形态不一致。
    这里把相邻 AIMessage 折叠：工具步骤按顺序累积，正文拼接非空片段。
    遇到 HumanMessage 即收尾当前 assistant 消息，开启新一轮。
    """
    return aggregate_messages(messages)


def _messages_with_xhs_sources(messages: list[dict], sources: list[dict]) -> list[dict]:
    """为历史回放的最新 assistant 消息追加已渲染的小红书来源链接。

    实时流式输出时，stream.py 会把这些链接作为额外 token 文本发送。
    LangGraph 只存模型 AIMessage，所以回放旧的纯 graph 会话时，也需要做同样的确定性后处理。
    """
    return messages_with_xhs_sources(messages, sources)


async def _snapshot(request: Request, meta: dict) -> dict:
    graph = request.app.state.graph
    snap = await graph.aget_state(_config(meta["thread_id"]))
    values = snap.values or {}
    ui_messages = await request.app.state.session_store.list_ui_messages(meta["thread_id"])
    messages = ui_messages or await reconstruct_messages_from_graph_history(
        graph,
        _config(meta["thread_id"]),
        values,
    )
    return {
        **meta,
        "messages": _messages_with_xhs_sources(messages, values.get("xhs_sources", []) or []),
        "day_plans": values.get("day_plans", []) or [],
        "budget": values.get("budget_check", {}) or {},
        "plan_version": values.get("plan_version", 0) or 0,
    }


@router.post("/api/sessions")
async def create_session(request: Request):
    return await request.app.state.session_store.create_session()


@router.get("/api/sessions")
async def list_sessions(request: Request):
    return {"sessions": await request.app.state.session_store.list_sessions()}


@router.get("/api/sessions/{thread_id}")
async def get_session(thread_id: str, request: Request):
    meta = await request.app.state.session_store.get_session(thread_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="会话不存在或已删除")
    return await _snapshot(request, meta)


@router.delete("/api/sessions/{thread_id}")
async def delete_session(thread_id: str, request: Request):
    deleted = await request.app.state.session_store.delete_session(thread_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="会话不存在或已删除")
    checkpointer = getattr(request.app.state, "checkpointer", None)
    if checkpointer is not None and hasattr(checkpointer, "adelete_thread"):
        await checkpointer.adelete_thread(thread_id)
    return Response(status_code=204)
