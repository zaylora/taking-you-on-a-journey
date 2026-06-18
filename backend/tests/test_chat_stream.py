"""流式链路单测（存活探针 + 校验层）。

M1 的全流式覆盖测试已由 Task 11 的 test_chat_stream_m2.py 接管。
此处仅保留不依赖图执行的两条测试：
- test_health：存活探针
- test_chat_rejects_empty_message：pydantic 校验层 422，图不执行
"""


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_chat_rejects_empty_message(client):
    resp = client.post("/api/chat", json={"message": ""})
    assert resp.status_code == 422
