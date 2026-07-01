# -*- coding: utf-8 -*-
import json

from app.tools.tool_result_storage import (
    maybe_persist_tool_result,
    read_persisted_tool_result_slice,
)


def test_small_tool_result_is_returned_unchanged(tmp_path):
    result = {"ok": True, "data": {"items": ["短结果"]}}

    out = maybe_persist_tool_result(
        result,
        tool_name="xhs_read_note",
        tool_call_id="call_small",
        storage_dir=tmp_path,
        threshold_chars=1000,
        preview_chars=100,
    )

    assert out == result


def test_large_tool_result_is_persisted_with_preview(tmp_path):
    result = {"ok": True, "data": {"content": "顺德攻略" * 200}}

    out = maybe_persist_tool_result(
        result,
        tool_name="xhs_read_note",
        tool_call_id="call_large",
        storage_dir=tmp_path,
        threshold_chars=100,
        preview_chars=30,
    )

    assert out["ok"] is True
    assert out["persisted"] is True
    assert out["tool_name"] == "xhs_read_note"
    assert out["original_chars"] > 100
    assert len(out["preview"]) <= 30
    assert out["result_id"].endswith(".json")

    stored = tmp_path / out["result_id"]
    assert stored.exists()
    assert json.loads(stored.read_text(encoding="utf-8")) == result


def test_read_persisted_tool_result_slice_returns_requested_window(tmp_path):
    result_id = "xhs_read_note-call_read.json"
    (tmp_path / result_id).write_text("0123456789", encoding="utf-8")

    out = read_persisted_tool_result_slice(
        result_id,
        offset=3,
        limit=4,
        storage_dir=tmp_path,
    )

    assert out == {
        "ok": True,
        "result_id": result_id,
        "offset": 3,
        "limit": 4,
        "total_chars": 10,
        "content": "3456",
        "has_more": True,
    }


def test_read_persisted_tool_result_rejects_path_traversal(tmp_path):
    outside = tmp_path.parent / "outside.json"
    outside.write_text("secret", encoding="utf-8")

    out = read_persisted_tool_result_slice(
        "../outside.json",
        offset=0,
        limit=10,
        storage_dir=tmp_path,
    )

    assert out["ok"] is False
    assert out["error"]["code"] == "invalid_result_id"
