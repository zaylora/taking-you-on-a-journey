"""M5 session API: anonymous local conversations are first-class resources."""
import json
import re
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.api.sessions import _snapshot
from app.services.session_store import SessionStore


def _extract_sse(body: str, event: str) -> dict:
    match = re.search(rf"event: {event}\r?\ndata: (.+)", body)
    assert match, f"no {event} event in:\n{body}"
    return json.loads(match.group(1).strip())


def test_create_list_get_and_delete_session(client):
    created = client.post("/api/sessions")
    assert created.status_code == 200
    payload = created.json()
    thread_id = payload["thread_id"]
    assert thread_id
    assert payload["title"] == "新的行程"

    listed = client.get("/api/sessions")
    assert listed.status_code == 200
    sessions = listed.json()["sessions"]
    assert any(s["thread_id"] == thread_id and s["title"] == "新的行程" for s in sessions)

    detail = client.get(f"/api/sessions/{thread_id}")
    assert detail.status_code == 200
    snapshot = detail.json()
    assert snapshot["thread_id"] == thread_id
    assert snapshot["title"] == "新的行程"
    assert snapshot["messages"] == []
    assert snapshot["day_plans"] == []
    assert snapshot["budget"] == {}
    assert snapshot["plan_version"] == 0

    deleted = client.delete(f"/api/sessions/{thread_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/sessions/{thread_id}").status_code == 404


def test_chat_rejects_deleted_session(client):
    thread_id = client.post("/api/sessions").json()["thread_id"]
    assert client.delete(f"/api/sessions/{thread_id}").status_code == 204

    body = client.post("/api/chat", json={"message": "继续规划", "thread_id": thread_id}).text
    error = _extract_sse(body, "error")
    assert "不存在" in error["message"] or "已删除" in error["message"]


@pytest.mark.anyio
async def test_session_store_persists_ui_messages(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.sqlite"))
    await store.setup()
    session = await store.create_session()

    await store.append_ui_message(session["thread_id"], "user", "帮我做顺德旅行攻略")
    await store.append_ui_message(
        session["thread_id"],
        "assistant",
        "这是顺德攻略。\n\n## 笔记来源\n- [顺德一日游](https://www.xiaohongshu.com/explore/note-1)",
        tool_steps=[
            {"tool": "research_xhs_travel_guide", "label": "研究小红书攻略", "status": "done"},
            {"tool": "finalize_plan", "label": "确认行程", "status": "done"},
        ],
    )

    messages = await store.list_ui_messages(session["thread_id"])

    assert messages == [
        {
            "role": "user",
            "content": "帮我做顺德旅行攻略",
            "kind": "text",
            "tool_steps": [],
        },
        {
            "role": "assistant",
            "content": "这是顺德攻略。\n\n## 笔记来源\n- [顺德一日游](https://www.xiaohongshu.com/explore/note-1)",
            "kind": "text",
            "tool_steps": [
                {"tool": "research_xhs_travel_guide", "label": "研究小红书攻略", "status": "done"},
                {"tool": "finalize_plan", "label": "确认行程", "status": "done"},
            ],
        },
    ]


@pytest.mark.anyio
async def test_snapshot_prefers_persisted_ui_messages_over_graph_messages(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.sqlite"))
    await store.setup()
    session = await store.create_session()
    await store.append_ui_message(session["thread_id"], "user", "帮我做顺德旅行攻略")
    await store.append_ui_message(
        session["thread_id"],
        "assistant",
        "实时完整答案。\n\n## 笔记来源\n- [顺德一日游](https://www.xiaohongshu.com/explore/note-1)",
        tool_steps=[
            {"tool": "research_xhs_travel_guide", "label": "research_xhs_travel_guide", "status": "done"},
        ],
    )

    class FakeGraph:
        async def aget_state(self, _config):
            return SimpleNamespace(values={
                "messages": [AIMessage(content="被压缩后的 graph 答案")],
                "xhs_sources": [{"title": "顺德一日游", "url": "https://www.xiaohongshu.com/explore/note-1"}],
                "day_plans": [],
                "budget_check": {},
                "plan_version": 0,
            })

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        graph=FakeGraph(),
        session_store=store,
    )))

    snapshot = await _snapshot(request, session)

    assert [(m["role"], m["content"]) for m in snapshot["messages"]] == [
        ("user", "帮我做顺德旅行攻略"),
        (
            "assistant",
            "实时完整答案。\n\n## 笔记来源\n- [顺德一日游](https://www.xiaohongshu.com/explore/note-1)",
        ),
    ]


@pytest.mark.anyio
async def test_snapshot_reconstructs_legacy_history_from_state_history(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.sqlite"))
    await store.setup()
    session = await store.create_session()

    class FakeGraph:
        async def aget_state(self, _config):
            return SimpleNamespace(values={
                "messages": [AIMessage(content="最终完整攻略。", tool_calls=[
                    {"name": "finalize_plan", "args": {}, "id": "latest"}
                ])],
                "xhs_sources": [],
                "day_plans": [],
                "budget_check": {},
                "plan_version": 0,
            })

        async def aget_state_history(self, _config):
            yield SimpleNamespace(values={
                "messages": [AIMessage(content="最终完整攻略。", tool_calls=[
                    {"name": "finalize_plan", "args": {}, "id": "latest"}
                ])]
            })
            yield SimpleNamespace(values={
                "messages": [
                    HumanMessage(content="帮我做广州两天旅行攻略"),
                    AIMessage(content="", tool_calls=[
                        {"name": "search_attractions", "args": {}, "id": "call_0"},
                        {"name": "search_restaurants", "args": {}, "id": "call_1"},
                    ]),
                    AIMessage(content="", tool_calls=[
                        {"name": "assemble_itinerary", "args": {}, "id": "call_2"},
                        {"name": "finalize_plan", "args": {}, "id": "call_3"},
                    ]),
                ]
            })

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        graph=FakeGraph(),
        session_store=store,
    )))

    snapshot = await _snapshot(request, session)

    assert [m["role"] for m in snapshot["messages"]] == ["user", "assistant"]
    assert snapshot["messages"][0]["content"] == "帮我做广州两天旅行攻略"
    assert snapshot["messages"][1]["content"] == "最终完整攻略。"
    assert [s["tool"] for s in snapshot["messages"][1]["tool_steps"]] == [
        "search_attractions",
        "search_restaurants",
        "assemble_itinerary",
        "finalize_plan",
    ]
