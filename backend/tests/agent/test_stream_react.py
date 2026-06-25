# -*- coding: utf-8 -*-
"""端到端：用脚本化假模型驱动 create_agent，验证 SSE token 放行与 EVENT_FINAL。"""
import json

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.messages import AIMessage

_CALLS = {"n": 0}


class _ScriptedModel(BaseChatModel):
    """第一轮直接产最终回复（无 tool_call），逐字流式。"""
    @property
    def _llm_type(self): return "scripted"
    def bind_tools(self, tools, **kw): return self
    def _generate(self, messages, stop=None, run_manager=None, **kw):
        return ChatResult(generations=[ChatGeneration(
            message=AIMessage(content="成都三天行程已为你准备好。"))])


@pytest.fixture
def react_client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    monkeypatch.setenv("AMAP_WEB_KEY", "amap-test-fake")
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "ck.sqlite"))
    monkeypatch.setattr("app.agent.build.build_llm", lambda *a, **k: _ScriptedModel())
    from app.core.config import get_settings
    get_settings.cache_clear()
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def _parse_sse(text):
    # 兼容 CRLF（Windows TestClient 返回 \r\n）和 LF
    text = text.replace("\r\n", "\n")
    events = []
    for block in text.strip().split("\n\n"):
        ev, data = None, None
        for line in block.splitlines():
            if line.startswith("event:"): ev = line[6:].strip()
            elif line.startswith("data:"): data = line[5:].strip()
        if ev: events.append((ev, json.loads(data) if data else None))
    return events


def test_final_answer_from_agent_message(react_client):
    resp = react_client.post("/api/chat", json={"message": "帮我规划成都3天"})
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    names = [e for e, _ in events]
    assert "final" in names
    final = next(d for e, d in events if e == "final")
    assert "成都三天行程" in final["answer"]
