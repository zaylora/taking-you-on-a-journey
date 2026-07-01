# -*- coding: utf-8 -*-
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.tools.tool_result_storage import read_persisted_tool_result_slice
from app.middleware.tool_result_persistence import ToolResultPersistenceMiddleware


def _request(tool_name: str):
    return SimpleNamespace(tool=SimpleNamespace(name=tool_name))


def test_large_tool_message_content_is_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv("TOOL_RESULT_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("TOOL_RESULT_PERSIST_THRESHOLD_CHARS", "20")
    monkeypatch.setenv("TOOL_RESULT_PREVIEW_CHARS", "8")
    from app.core.config import get_settings
    get_settings.cache_clear()

    message = ToolMessage(content="顺德攻略" * 20, tool_call_id="call_large")
    middleware = ToolResultPersistenceMiddleware()

    out = middleware.wrap_tool_call(_request("xhs_read_note"), lambda _request: message)

    envelope = json.loads(out.content)
    assert envelope["ok"] is True
    assert envelope["persisted"] is True
    assert envelope["tool_name"] == "xhs_read_note"
    assert envelope["preview"] == ("顺德攻略" * 20)[:8]
    assert (tmp_path / envelope["result_id"]).exists()


def test_small_tool_message_content_is_returned_unchanged(monkeypatch, tmp_path):
    monkeypatch.setenv("TOOL_RESULT_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("TOOL_RESULT_PERSIST_THRESHOLD_CHARS", "1000")
    from app.core.config import get_settings
    get_settings.cache_clear()

    message = ToolMessage(content="短结果", tool_call_id="call_small")
    middleware = ToolResultPersistenceMiddleware()

    out = middleware.wrap_tool_call(_request("xhs_read_note"), lambda _request: message)

    assert out is message
    assert list(tmp_path.iterdir()) == []


def test_large_command_tool_message_content_is_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv("TOOL_RESULT_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("TOOL_RESULT_PERSIST_THRESHOLD_CHARS", "20")
    monkeypatch.setenv("TOOL_RESULT_PREVIEW_CHARS", "6")
    from app.core.config import get_settings
    get_settings.cache_clear()

    message = ToolMessage(content="评论" * 30, tool_call_id="call_cmd")
    command = Command(update={"messages": [message], "xhs_sources": [{"title": "A"}]})
    middleware = ToolResultPersistenceMiddleware()

    out = middleware.wrap_tool_call(_request("research_xhs_travel_guide"), lambda _request: command)

    assert out.update["xhs_sources"] == [{"title": "A"}]
    persisted_message = out.update["messages"][0]
    envelope = json.loads(persisted_message.content)
    assert envelope["persisted"] is True
    assert envelope["tool_name"] == "research_xhs_travel_guide"
    assert envelope["preview"] == ("评论" * 30)[:6]
    assert persisted_message.tool_call_id == "call_cmd"


def test_excluded_tool_is_not_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv("TOOL_RESULT_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("TOOL_RESULT_PERSIST_THRESHOLD_CHARS", "20")
    from app.core.config import get_settings
    get_settings.cache_clear()

    message = ToolMessage(content="最终方案" * 30, tool_call_id="call_final")
    middleware = ToolResultPersistenceMiddleware()

    out = middleware.wrap_tool_call(_request("finalize_plan"), lambda _request: message)

    assert out is message
    assert list(tmp_path.iterdir()) == []


def test_persisted_envelope_can_be_read_back(monkeypatch, tmp_path):
    monkeypatch.setenv("TOOL_RESULT_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("TOOL_RESULT_PERSIST_THRESHOLD_CHARS", "20")
    monkeypatch.setenv("TOOL_RESULT_PREVIEW_CHARS", "4")
    from app.core.config import get_settings
    get_settings.cache_clear()

    content = "0123456789" * 10
    message = ToolMessage(content=content, tool_call_id="call_read")
    middleware = ToolResultPersistenceMiddleware()

    out = middleware.wrap_tool_call(_request("xhs_read_note"), lambda _request: message)

    envelope = json.loads(out.content)
    read = read_persisted_tool_result_slice(
        envelope["result_id"],
        offset=2,
        limit=5,
        storage_dir=tmp_path,
    )
    assert read["content"] == content[2:7]


@pytest.mark.asyncio
async def test_async_tool_call_is_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv("TOOL_RESULT_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("TOOL_RESULT_PERSIST_THRESHOLD_CHARS", "20")
    from app.core.config import get_settings
    get_settings.cache_clear()

    message = ToolMessage(content="异步结果" * 20, tool_call_id="call_async")
    middleware = ToolResultPersistenceMiddleware()

    async def _handler(_request):
        return message

    out = await middleware.awrap_tool_call(_request("xhs_read_note"), _handler)

    envelope = json.loads(out.content)
    assert envelope["persisted"] is True
    assert (tmp_path / envelope["result_id"]).exists()
