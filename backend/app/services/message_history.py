"""Helpers for converting graph messages into replayable UI messages."""
from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.services.tool_labels import build_tool_label

_XHS_SOURCE_LIMIT = 6
_XHS_SOURCE_FALLBACK_TITLE = "小红书笔记"


def render_xhs_sources(sources: list[dict], *, limit: int = _XHS_SOURCE_LIMIT) -> str:
    """Render xhs_sources as markdown source links. Empty or URL-less input returns blank."""
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


def extract_content(message) -> str:
    """Extract text content from a message, handling list-type content."""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
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


def is_summarization_message(message) -> bool:
    return getattr(message, "additional_kwargs", {}).get("lc_source") == "summarization"


def tool_steps(message) -> list[dict]:
    return [
        {
            "tool": tc["name"],
            "label": build_tool_label(tc.get("name"), tc.get("args") or {}),
            "status": "done",
        }
        for tc in (getattr(message, "tool_calls", None) or [])
    ]


def _tool_segments(message) -> list[dict]:
    """把一个 AIMessage 的 tool_calls 转成 tool 段（历史一律 done）。"""
    return [
        {
            "kind": "tool",
            "tool": tc["name"],
            "label": build_tool_label(tc.get("name"), tc.get("args") or {}),
            "status": "done",
        }
        for tc in (getattr(message, "tool_calls", None) or [])
    ]


def build_segments(messages) -> list[dict]:
    """把一轮内的 AIMessage 序列按出现顺序转成交错的 text/tool 段。

    意图：让历史回放与实时流呈现同一形态——文本与工具按时间顺序交错，
    而非「正文一坨 + 工具一坨」。ToolMessage/SystemMessage 跳过；空文本块不产出 text 段。
    """
    segments: list[dict] = []
    for message in messages:
        if isinstance(message, (ToolMessage, SystemMessage)):
            continue
        if isinstance(message, HumanMessage):
            if is_summarization_message(message):
                continue
            continue  # user 段由调用方处理，这里只攒 assistant 内容
        if isinstance(message, AIMessage):
            text = extract_content(message)
            if text:
                segments.append({"kind": "text", "text": text})
            segments.extend(_tool_segments(message))
    return segments


def segments_for_assistant(messages) -> list[dict]:
    """仅返回最后一个用户回合之后的 assistant segments。"""
    last_human = -1
    for idx, message in enumerate(messages):
        if isinstance(message, HumanMessage) and not is_summarization_message(message):
            last_human = idx
    return build_segments(messages[last_human + 1:])


def aggregate_messages(messages) -> list[dict]:
    """Collapse ReAct AIMessage groups into one assistant message per user turn."""
    result: list[dict] = []
    current_ai: dict | None = None
    for message in messages:
        if isinstance(message, (ToolMessage, SystemMessage)):
            continue
        if isinstance(message, HumanMessage):
            if is_summarization_message(message):
                continue
            current_ai = None
            result.append({"role": "user", "content": extract_content(message), "kind": "text"})
        elif isinstance(message, AIMessage):
            content = extract_content(message)
            if current_ai is None:
                current_ai = {
                    "role": "assistant",
                    "content": content,
                    "kind": "text",
                    "tool_steps": tool_steps(message),
                }
                result.append(current_ai)
            else:
                current_ai["tool_steps"].extend(tool_steps(message))
                if content:
                    current_ai["content"] = (
                        f"{current_ai['content']}{content}" if current_ai["content"] else content
                    )
        elif isinstance(message, BaseMessage):
            current_ai = None
            result.append({"role": message.type, "content": extract_content(message), "kind": "text"})
        elif isinstance(message, dict):
            current_ai = None
            raw = message.get("content", "")
            content = raw if isinstance(raw, str) else extract_content(raw)
            result.append({
                "role": message.get("role", "assistant"),
                "content": content,
                "kind": message.get("kind", "text"),
            })
        else:
            current_ai = None
            result.append({"role": "assistant", "content": str(message), "kind": "text"})
    return result


def messages_with_xhs_sources(messages: list[dict], sources: list[dict]) -> list[dict]:
    """Append rendered xhs source links to the latest assistant message for history replay."""
    sources_md = render_xhs_sources(sources)
    if not sources_md:
        return messages
    result = [dict(message) for message in messages]
    for message in reversed(result):
        if message.get("role") == "assistant":
            content = message.get("content") or ""
            if "## 笔记来源" not in content:
                message["content"] = f"{content}{sources_md}" if content else sources_md.lstrip()
            break
    return result


def _append_missing_tool_types(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """Append tool types absent from the chosen longest chain, preserving duplicates already there."""
    merged = list(existing)
    seen_tools = {step.get("tool") for step in merged}
    for step in incoming:
        if step.get("tool") in seen_tools:
            continue
        seen_tools.add(step.get("tool"))
        merged.append({**step, "status": "done"})
    return merged


def reconstruct_messages_from_history(history_values: list[dict]) -> list[dict]:
    """Rebuild UI history from checkpoint history when latest graph state was compressed.

    LangGraph history is returned newest-first. Newer snapshots often contain final
    assistant text but fewer early tool calls; older snapshots often contain the original
    HumanMessage and fuller ReAct tool chain but no final text. For a one-turn legacy
    session, merge those complementary pieces into the same shape realtime streaming uses.
    """
    if not history_values:
        return []

    user_messages: list[dict] = []
    assistant_content = ""
    assistant_tools: list[dict] = []
    tool_candidates: list[list[dict]] = []

    for values in history_values:
        aggregated = aggregate_messages((values or {}).get("messages", []) or [])
        for message in aggregated:
            if message.get("role") == "user":
                content = message.get("content") or ""
                if content and all(existing["content"] != content for existing in user_messages):
                    user_messages.append({
                        "role": "user",
                        "content": content,
                        "kind": message.get("kind", "text"),
                    })
            elif message.get("role") == "assistant":
                content = message.get("content") or ""
                if content and not assistant_content:
                    assistant_content = content

    for values in reversed(history_values):
        aggregated = aggregate_messages((values or {}).get("messages", []) or [])
        for message in aggregated:
            if message.get("role") == "assistant":
                steps = [{**step, "status": "done"} for step in (message.get("tool_steps") or [])]
                if steps:
                    tool_candidates.append(steps)

    if tool_candidates:
        assistant_tools = max(tool_candidates, key=len)
        for steps in tool_candidates:
            assistant_tools = _append_missing_tool_types(assistant_tools, steps)

    if not user_messages:
        latest_messages = aggregate_messages((history_values[0] or {}).get("messages", []) or [])
        return latest_messages

    result = user_messages[:1]
    if assistant_content or assistant_tools:
        result.append({
            "role": "assistant",
            "content": assistant_content,
            "kind": "text",
            "tool_steps": assistant_tools,
        })
    return result


async def reconstruct_messages_from_graph_history(graph, config: dict, latest_values: dict) -> list[dict]:
    """Read graph state history and reconstruct replayable UI messages.

    Falls back to the latest state when the graph does not expose history or has no
    persisted history for the thread.
    """
    history_values: list[dict] = []
    if hasattr(graph, "aget_state_history"):
        async for snapshot in graph.aget_state_history(config):
            history_values.append(snapshot.values or {})
    if not history_values:
        history_values = [latest_values]
    return reconstruct_messages_from_history(history_values)
