"""桥接层（M2）：astream_events(v2) → SSE。区分暂停(clarify)与完成(final)。
🔬 探针实测：interrupt 暂停时流干净结束；流后 aget_state().tasks[].interrupts[0].value 取澄清 payload；
token 仅放行 metadata.langgraph_node=="summarize"。
"""
import json
import uuid

from langgraph.types import Command

from app.core.constants import (
    EVENT_SESSION, EVENT_NODE_START, EVENT_TOKEN, EVENT_NODE_END,
    EVENT_CLARIFY, EVENT_FINAL, EVENT_ERROR, NODES, NODE_LABELS,
)
from app.graph.builder import build_graph

GRAPH = build_graph()


def _sse(event: str, payload: dict) -> dict:
    return {"event": event, "data": json.dumps(payload, ensure_ascii=False)}


async def sse_events(message: str, thread_id: str | None, request):
    new_session = thread_id is None
    if new_session:
        thread_id = uuid.uuid4().hex  # ⚠️ 运行期生成
    config = {"configurable": {"thread_id": thread_id}}
    try:
        if new_session:
            yield _sse(EVENT_SESSION, {"thread_id": thread_id})
            stream_input = {"query": message, "messages": [],
                            "clarified": False, "clarify_round": 0}
        else:
            snap = await GRAPH.aget_state(config)
            pending = any(t.interrupts for t in snap.tasks) if snap and snap.tasks else False
            stream_input = Command(resume=message) if pending else {"query": message}

        async for ev in GRAPH.astream_events(stream_input, config=config, version="v2"):
            if await request.is_disconnected():
                break
            kind, name = ev["event"], ev.get("name")
            if kind == "on_chain_start" and name in NODES:
                yield _sse(EVENT_NODE_START, {"node": name, "label": NODE_LABELS.get(name, "")})
            elif kind == "on_chat_model_stream" and ev.get("metadata", {}).get("langgraph_node") == "summarize":
                tok = ev["data"]["chunk"].content
                if tok:
                    yield _sse(EVENT_TOKEN, {"text": tok})
            elif kind == "on_chain_end" and name in NODES:
                yield _sse(EVENT_NODE_END, {"node": name})

        # 流后判定：暂停等澄清 or 编排完成
        snap = await GRAPH.aget_state(config)
        interrupts = [t.interrupts[0] for t in (snap.tasks or []) if t.interrupts]
        if interrupts:
            yield _sse(EVENT_CLARIFY, interrupts[0].value)
        else:
            answer = (snap.values or {}).get("summary", "")
            day_plans = (snap.values or {}).get("day_plans", [])
            yield _sse(EVENT_FINAL, {"answer": answer, "day_plans": day_plans})
    except Exception:  # noqa: BLE001 —— 脱敏：不泄露 Key/堆栈
        yield _sse(EVENT_ERROR, {"message": "生成失败，请重试"})
