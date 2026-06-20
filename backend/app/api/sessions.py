"""M5 anonymous conversation session endpoints."""
from fastapi import APIRouter, HTTPException, Request, Response
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

router = APIRouter()


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _message_to_dict(message) -> dict:
    if isinstance(message, HumanMessage):
        return {"role": "user", "content": message.content, "kind": "text"}
    if isinstance(message, AIMessage):
        return {"role": "assistant", "content": message.content, "kind": "text"}
    if isinstance(message, BaseMessage):
        return {"role": message.type, "content": message.content, "kind": "text"}
    if isinstance(message, dict):
        return {
            "role": message.get("role", "assistant"),
            "content": message.get("content", ""),
            "kind": message.get("kind", "text"),
        }
    return {"role": "assistant", "content": str(message), "kind": "text"}


async def _snapshot(request: Request, meta: dict) -> dict:
    graph = request.app.state.graph
    snap = await graph.aget_state(_config(meta["thread_id"]))
    values = snap.values or {}
    return {
        **meta,
        "messages": [_message_to_dict(m) for m in values.get("messages", [])],
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
