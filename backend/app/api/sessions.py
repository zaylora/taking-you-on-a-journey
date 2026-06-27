"""M5 anonymous conversation session endpoints."""
from fastapi import APIRouter, HTTPException, Request, Response
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.core.constants import TOOL_LABELS

router = APIRouter()


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _extract_content(message) -> str:
    """Extract text content from a message, handling list-type content."""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # Multi-modal or tool-use messages: join text parts
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
        return "\n".join(parts)
    if content is not None:
        return str(content)
    return ""


_SKIP_TYPES = (ToolMessage, SystemMessage)


def _is_summarization_message(message) -> bool:
    return getattr(message, "additional_kwargs", {}).get("lc_source") == "summarization"


def _tool_steps(message) -> list[dict]:
    return [
        {"tool": tc["name"], "label": TOOL_LABELS.get(tc["name"], tc["name"]), "status": "done"}
        for tc in (getattr(message, "tool_calls", None) or [])
    ]


def _aggregate_messages(messages) -> list[dict]:
    """把 ReAct 一轮内的多个 AIMessage 聚合成单条 assistant 消息。

    单 Agent ReAct 一次回答会产生多个 AIMessage（每轮 model 决策一个，
    中间轮往往只有 tool_calls、正文为空，最后一轮才有正文）。历史快照若逐条
    渲染会得到多条空气泡，且与实时流「单条消息内聚合工具链」的形态不一致。
    这里把相邻 AIMessage 折叠：工具步骤按顺序累积，正文拼接非空片段。
    遇到 HumanMessage 即收尾当前 assistant 消息，开启新一轮。
    """
    result: list[dict] = []
    current_ai: dict | None = None
    for message in messages:
        if isinstance(message, _SKIP_TYPES):
            continue
        if isinstance(message, HumanMessage):
            if _is_summarization_message(message):
                continue
            current_ai = None
            result.append({"role": "user", "content": _extract_content(message), "kind": "text"})
        elif isinstance(message, AIMessage):
            content = _extract_content(message)
            if current_ai is None:
                current_ai = {
                    "role": "assistant",
                    "content": content,
                    "kind": "text",
                    "tool_steps": _tool_steps(message),
                }
                result.append(current_ai)
            else:
                current_ai["tool_steps"].extend(_tool_steps(message))
                if content:
                    current_ai["content"] = (
                        f"{current_ai['content']}{content}" if current_ai["content"] else content
                    )
        elif isinstance(message, BaseMessage):
            current_ai = None
            result.append({"role": message.type, "content": _extract_content(message), "kind": "text"})
        elif isinstance(message, dict):
            current_ai = None
            raw = message.get("content", "")
            content = raw if isinstance(raw, str) else _extract_content(raw)
            result.append({
                "role": message.get("role", "assistant"),
                "content": content,
                "kind": message.get("kind", "text"),
            })
        else:
            current_ai = None
            result.append({"role": "assistant", "content": str(message), "kind": "text"})
    return result


async def _snapshot(request: Request, meta: dict) -> dict:
    graph = request.app.state.graph
    snap = await graph.aget_state(_config(meta["thread_id"]))
    values = snap.values or {}
    return {
        **meta,
        "messages": _aggregate_messages(values.get("messages", [])),
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
