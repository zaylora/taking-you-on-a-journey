"""流式链路单测（存活探针 + 校验层）。

M1 的全流式覆盖测试已由 Task 11 的 test_chat_stream_m2.py 接管。
此处仅保留不依赖图执行的两条测试：
- test_health：存活探针
- test_chat_rejects_empty_message：pydantic 校验层 422，图不执行
"""
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from app.graph.stream import sse_events
from app.services.session_store import SessionStore


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_chat_rejects_empty_message(client):
    resp = client.post("/api/chat", json={"message": ""})
    assert resp.status_code == 422


from app.graph.stream import render_xhs_sources


def test_render_xhs_sources_basic():
    md = render_xhs_sources([
        {"title": "顺德一日游", "url": "https://www.xiaohongshu.com/explore/n1?xsec_token=t1&xsec_source=pc_search"},
        {"title": "", "url": "https://www.xiaohongshu.com/explore/n2"},
    ])
    assert md.startswith("\n\n## 笔记来源\n")
    assert "- [顺德一日游](https://www.xiaohongshu.com/explore/n1?xsec_token=t1&xsec_source=pc_search)" in md
    assert "- [小红书笔记](https://www.xiaohongshu.com/explore/n2)" in md


def test_render_xhs_sources_empty_returns_blank():
    assert render_xhs_sources([]) == ""


def test_render_xhs_sources_skips_missing_url():
    """验证无 url 的记录被跳过，且不被 limit 掩盖。"""
    md = render_xhs_sources(
        [
            {"title": "A", "url": "https://x/1"},
            {"title": "B", "url": ""},
            {"title": "C", "url": "https://x/3"},
        ],
        limit=6,
    )
    assert "[A](https://x/1)" in md
    assert "B" not in md       # 无 url 跳过
    assert "[C](https://x/3)" in md  # limit 足够大，C 应被渲染


def test_render_xhs_sources_limits():
    """验证 limit 截断：仅渲染前 N 条，超出部分不出现。"""
    md = render_xhs_sources(
        [
            {"title": "A", "url": "https://x/1"},
            {"title": "B", "url": "https://x/2"},
            {"title": "C", "url": "https://x/3"},
        ],
        limit=2,
    )
    assert "[A](https://x/1)" in md
    assert "[B](https://x/2)" in md
    assert "C" not in md       # 超出 limit


class _FakeGraphWithSources:
    def __init__(self):
        self._state_calls = 0

    async def aget_state(self, _config):
        self._state_calls += 1
        if self._state_calls == 1:
            return SimpleNamespace(values={"xhs_sources": []})
        return SimpleNamespace(values={
            "messages": [AIMessage(content="这是顺德攻略。")],
            "xhs_sources": [
                {"title": "顺德一日游", "url": "https://www.xiaohongshu.com/explore/note-1"},
            ],
            "day_plans": [],
            "budget_check": {},
            "plan_version": 0,
            "changed_days": [],
        })

    async def astream_events(self, _stream_input, *, config, version):
        yield {
            "event": "on_tool_start",
            "name": "research_xhs_travel_guide",
            "data": {"input": {"city": "顺德", "days": 1, "travel_style": "美食"}},
        }
        yield {"event": "on_tool_end", "name": "research_xhs_travel_guide"}
        yield {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="这是顺德攻略。")}}


class _FakeGraphWithPriorHistory:
    def __init__(self):
        self._state_calls = 0

    async def aget_state(self, _config):
        self._state_calls += 1
        if self._state_calls == 1:
            return SimpleNamespace(values={
                "messages": [
                    HumanMessage(content="旧问题"),
                    AIMessage(content="旧答案"),
                ],
                "xhs_sources": [],
            })
        return SimpleNamespace(values={
            "messages": [
                HumanMessage(content="旧问题"),
                AIMessage(content="旧答案"),
                HumanMessage(content="新问题"),
                AIMessage(content="新答案"),
            ],
            "xhs_sources": [],
            "day_plans": [],
            "budget_check": {},
            "plan_version": 0,
            "changed_days": [],
        })

    async def astream_events(self, _stream_input, *, config, version):
        yield {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="新答案")}}


class _FakeGraphThatFails:
    async def aget_state(self, _config):
        return SimpleNamespace(values={})

    async def astream_events(self, _stream_input, *, config, version):
        if False:
            yield {}
        raise RuntimeError("boom")


@pytest.mark.anyio
async def test_sse_events_persists_ui_history_matching_realtime_stream(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.sqlite"))
    await store.setup()
    session = await store.create_session()
    graph = _FakeGraphWithSources()

    async def _is_disconnected():
        return False

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(graph=graph, session_store=store)),
        is_disconnected=_is_disconnected,
    )

    events = [
        event async for event in sse_events("帮我做顺德旅行攻略", session["thread_id"], request)
    ]

    token_text = "".join(
        json.loads(event["data"])["text"] for event in events if event["event"] == "token"
    )
    messages = await store.list_ui_messages(session["thread_id"])

    assert token_text == (
        "这是顺德攻略。\n\n## 笔记来源\n"
        "- [顺德一日游](https://www.xiaohongshu.com/explore/note-1)"
    )
    assert messages == [
        {"role": "user", "content": "帮我做顺德旅行攻略", "kind": "text", "tool_steps": []},
        {
            "role": "assistant",
            "content": token_text,
            "kind": "text",
            "tool_steps": [
                {
                    "tool": "research_xhs_travel_guide",
                    "label": "研究顺德1天美食小红书攻略",
                    "status": "done",
                },
            ],
        },
    ]

    tool_call = next(event for event in events if event["event"] == "tool_call")
    assert json.loads(tool_call["data"]) == {
        "tool": "research_xhs_travel_guide",
        "label": "研究顺德1天美食小红书攻略",
    }


@pytest.mark.anyio
async def test_sse_events_seeds_existing_graph_history_before_persisting_new_turn(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.sqlite"))
    await store.setup()
    session = await store.create_session()
    graph = _FakeGraphWithPriorHistory()

    async def _is_disconnected():
        return False

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(graph=graph, session_store=store)),
        is_disconnected=_is_disconnected,
    )

    [event async for event in sse_events("新问题", session["thread_id"], request)]

    messages = await store.list_ui_messages(session["thread_id"])

    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "旧问题"),
        ("assistant", "旧答案"),
        ("user", "新问题"),
        ("assistant", "新答案"),
    ]


@pytest.mark.anyio
async def test_sse_events_persists_error_history_matching_realtime_stream(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.sqlite"))
    await store.setup()
    session = await store.create_session()

    async def _is_disconnected():
        return False

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(graph=_FakeGraphThatFails(), session_store=store)),
        is_disconnected=_is_disconnected,
    )

    events = [event async for event in sse_events("继续规划", session["thread_id"], request)]
    messages = await store.list_ui_messages(session["thread_id"])

    assert events[-1]["event"] == "error"
    assert messages == [
        {"role": "user", "content": "继续规划", "kind": "text", "tool_steps": []},
        {"role": "assistant", "content": "生成失败，请重试", "kind": "error", "tool_steps": []},
    ]
