"""桥接层（M2）：astream_events(v2) → SSE。区分暂停(clarify)与完成(final)。
🔬 探针实测：interrupt 暂停时流干净结束；流后 aget_state().tasks[].interrupts[0].value 取澄清 payload；
token 仅放行 metadata.langgraph_node=="summarize"。
"""
import json
import logging

from langchain_core.messages import HumanMessage
from langgraph.types import Command

logger = logging.getLogger(__name__)

from app.core.constants import (
    EVENT_SESSION, EVENT_NODE_START, EVENT_TOKEN, EVENT_NODE_END,
    EVENT_CLARIFY, EVENT_FINAL, EVENT_ERROR, EVENT_PLAN_PATCH, EVENT_TITLE, NODES, NODE_LABELS,
    EVENT_TOOL_CALL, EVENT_TOOL_RESULT, TOOL_LABELS,
)
from app.services.session_store import DEFAULT_TITLE, title_from_message


def _sse(event: str, payload: dict) -> dict:
    return {"event": event, "data": json.dumps(payload, ensure_ascii=False)}


def _as_text(content) -> str:
    """归一化消息 content 为纯文本。

    OpenAI 系返回 str；Anthropic 系返回结构化 list（如
    [{"type": "text", "text": "…"}]），需抽取并拼接其中的文本块，
    否则前端按字符串渲染会得到 [object Object]。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type", "text") == "text" and "text" in block:
                    parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content) if content else ""


async def sse_events(message: str, thread_id: str | None, request):
    graph = request.app.state.graph
    session_store = request.app.state.session_store
    new_session = thread_id is None
    if new_session:
        session = await session_store.create_session()
        thread_id = session["thread_id"]
    else:
        session = await session_store.get_session(thread_id)
        if session is None:
            yield _sse(EVENT_ERROR, {"message": "会话不存在或已删除，请新建会话后重试"})
            return
    config = {"configurable": {"thread_id": thread_id}}
    try:
        if new_session:
            yield _sse(EVENT_SESSION, {"thread_id": thread_id})
            stream_input = {"messages": [HumanMessage(content=message)]}
        else:
            snap = await graph.aget_state(config)
            pending = any(t.interrupts for t in snap.tasks) if snap and snap.tasks else False
            stream_input = (
                Command(resume=message)
                if pending
                else {"messages": [HumanMessage(content=message)]}
            )

        async for ev in graph.astream_events(stream_input, config=config, version="v2"):
            if await request.is_disconnected():
                break
            kind, name = ev["event"], ev.get("name")
            if kind == "on_chat_model_stream":
                chunk = ev["data"]["chunk"]
                text = _as_text(chunk.content)
                if text:
                    yield _sse(EVENT_TOKEN, {"text": text})
            elif kind == "on_tool_start":
                yield _sse(EVENT_TOOL_CALL, {"tool": name, "label": TOOL_LABELS.get(name, name)})
            elif kind == "on_tool_end":
                yield _sse(EVENT_TOOL_RESULT, {"tool": name, "label": TOOL_LABELS.get(name, name)})
            elif kind == "on_chain_start" and name in NODES:
                yield _sse(EVENT_NODE_START, {"node": name, "label": NODE_LABELS.get(name, "")})
            elif kind == "on_chain_end" and name in NODES:
                yield _sse(EVENT_NODE_END, {"node": name})

        # 流后判定：暂停等澄清 or 编排完成
        snap = await graph.aget_state(config)
        interrupts = [t.interrupts[0] for t in (snap.tasks or []) if t.interrupts]
        if interrupts:
            yield _sse(EVENT_CLARIFY, interrupts[0].value)
        else:
            values = snap.values or {}
            messages = values.get("messages", []) or []
            answer = ""
            for m in reversed(messages):
                content = getattr(m, "content", None)
                msg_type = getattr(m, "type", "")
                if msg_type == "ai" and content:
                    answer = _as_text(content)
                    break
            day_plans = values.get("day_plans", [])
            budget = values.get("budget_check", {})
            plan_version = values.get("plan_version", 0) or 0
            changed_days = values.get("changed_days", []) or []
            if changed_days:
                yield _sse(EVENT_PLAN_PATCH, {"plan_version": plan_version, "changed_days": changed_days})
            title = None
            if session and session.get("title") == DEFAULT_TITLE:
                title = title_from_message(message)
            updated = await session_store.touch_session(thread_id, title=title)
            yield _sse(EVENT_FINAL, {
                "answer": answer,
                "day_plans": day_plans,
                "budget": budget,
                "plan_version": plan_version,
            })
            if title and updated:
                yield _sse(EVENT_TITLE, {"thread_id": thread_id, "title": updated["title"]})
    except Exception:  # noqa: BLE001 —— 前端脱敏：不泄露 Key/堆栈；但服务端必须留真因
        logger.exception("sse_events 处理失败 thread_id=%s", thread_id)
        yield _sse(EVENT_ERROR, {"message": "生成失败，请重试"})
