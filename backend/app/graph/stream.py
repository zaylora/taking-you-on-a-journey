"""桥接层：把 LangGraph 的 astream_events(v2) 翻译为 SSE 事件 dict。

事件映射（已用探针实测确认取值）：
  on_chain_start(name in NODES)  -> node_start {"node": name}
  on_chat_model_stream           -> token     {"text": chunk.content}
  on_chain_end(name in NODES)    -> node_end  {"node": name}
  迭代结束                        -> final     {"answer": 累加文本}
  异常                            -> error     {"message": 脱敏文案}

结束信号统一用 final（禁用 [DONE] 哨兵）。所有 data 用 ensure_ascii=False 序列化为单行。
"""
import json

from app.core.constants import (
    EVENT_NODE_START,
    EVENT_TOKEN,
    EVENT_NODE_END,
    EVENT_FINAL,
    EVENT_ERROR,
)
from app.graph.builder import build_graph

GRAPH = build_graph()
NODES = {"dispatch", "summarize"}


def _sse(event: str, payload: dict) -> dict:
    return {"event": event, "data": json.dumps(payload, ensure_ascii=False)}


async def sse_events(query: str, request):
    """生成 SSE 事件 dict 流，交给 EventSourceResponse 编码下发。

    注意：客户端断开时 EventSourceResponse 会取消本协程并抛 asyncio.CancelledError，
    它继承自 BaseException，不会被下面的 `except Exception` 吞掉，可正常向上传播收尾。
    """
    state = {"query": query, "messages": [], "summary": ""}
    answer = ""
    try:
        async for ev in GRAPH.astream_events(state, version="v2"):
            # 客户端断开则尽早停止，避免无谓的 LLM 消耗与任务泄漏
            if await request.is_disconnected():
                break

            kind = ev["event"]
            name = ev.get("name")

            if kind == "on_chain_start" and name in NODES:
                yield _sse(EVENT_NODE_START, {"node": name})
            elif kind == "on_chat_model_stream":
                tok = ev["data"]["chunk"].content
                if tok:
                    answer += tok
                    yield _sse(EVENT_TOKEN, {"text": tok})
            elif kind == "on_chain_end" and name in NODES:
                yield _sse(EVENT_NODE_END, {"node": name})

        yield _sse(EVENT_FINAL, {"answer": answer})
    except Exception:  # noqa: BLE001 —— 脱敏：不泄露 Key/堆栈
        yield _sse(EVENT_ERROR, {"message": "生成失败，请重试"})
