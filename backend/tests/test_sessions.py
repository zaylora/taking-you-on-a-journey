"""M5 session API: anonymous local conversations are first-class resources."""
import json
import re


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
