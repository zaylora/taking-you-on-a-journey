"""流式链路单测：对 LLM 工厂打桩，不依赖真实 Key/网络。

要点：
- client fixture 来自 conftest.py（假 Key + 清 settings 缓存）。
- 流式测试自行 monkeypatch summarize 节点引用的 build_llm，返回可流式的 GenericFakeChatModel。
- 断言 SSE 响应中出现 `event: token` 与 `event: final`。
"""
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage


def _fake_build_llm(*args, **kwargs):
    # 每次返回新实例：GenericFakeChatModel 的 messages 是一次性 iterator。
    return GenericFakeChatModel(messages=iter([AIMessage(content="东京 三日 行程 已 生成")]))


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_chat_stream_emits_token_and_final(client, monkeypatch):
    monkeypatch.setattr("app.graph.nodes.summarize.build_llm", _fake_build_llm)
    resp = client.post("/api/chat", json={"message": "帮我规划三天东京行程"})
    assert resp.status_code == 200
    body = resp.text
    assert "event: token" in body, body
    assert "event: final" in body, body
    # final 的 answer 应包含打桩模型输出片段
    assert "行程" in body


def test_chat_rejects_empty_message(client):
    resp = client.post("/api/chat", json={"message": ""})
    assert resp.status_code == 422
