"""桥接层：astream_events(v2) → SSE。"""
import json
import logging

from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

from app.core.constants import (
    EVENT_SESSION, EVENT_NODE_START, EVENT_TOKEN, EVENT_NODE_END,
    EVENT_FINAL, EVENT_ERROR, EVENT_PLAN_PATCH, EVENT_TITLE, NODE_LABELS,
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


_XHS_SOURCE_LIMIT = 6
_XHS_SOURCE_FALLBACK_TITLE = "小红书笔记"


def render_xhs_sources(sources: list[dict], *, limit: int = _XHS_SOURCE_LIMIT) -> str:
    """把 xhs_sources 渲染成 markdown「## 笔记来源」列表。空或全无 url 时返回空串。"""
    lines = []
    for src in sources or []:
        url = (src.get("url") or "").strip()
        if not url:
            continue
        title = (src.get("title") or "").strip() or _XHS_SOURCE_FALLBACK_TITLE
        lines.append(f"- [{title}]({url})")
        if len(lines) >= limit:
            break
    if not lines:
        return ""
    return "\n\n## 笔记来源\n" + "\n".join(lines)


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

        prior_state = await graph.aget_state(config)
        prior_source_count = len((prior_state.values or {}).get("xhs_sources", []) or [])

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
            elif kind == "on_chain_start" and name in NODE_LABELS:
                yield _sse(EVENT_NODE_START, {"node": name, "label": NODE_LABELS[name]})
            elif kind == "on_chain_end" and name in NODE_LABELS:
                yield _sse(EVENT_NODE_END, {"node": name})

        snap = await graph.aget_state(config)
        values = snap.values or {}
        messages = values.get("messages", []) or []
        answer = ""
        for m in reversed(messages):
            content = getattr(m, "content", None)
            msg_type = getattr(m, "type", "")
            if msg_type == "ai" and content:
                answer = _as_text(content)
                break
        xhs_sources = values.get("xhs_sources", []) or []
        if answer and len(xhs_sources) > prior_source_count:
            sources_md = render_xhs_sources(xhs_sources)
            if sources_md:
                yield _sse(EVENT_TOKEN, {"text": sources_md})
                answer = answer + sources_md
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
