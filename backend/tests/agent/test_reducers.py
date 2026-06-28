# -*- coding: utf-8 -*-
"""xhs_sources reducer：去重 / 保留先出现者 / 截断到 limit / 并发增量合并。"""
from app.agent.reducers import merge_xhs_sources


def _src(note_id, title="t"):
    return {"note_id": note_id, "title": title, "url": f"https://x/{note_id}"}


def test_merge_dedupes_by_note_id_keeping_first():
    existing = [_src("a", "旧a"), _src("b", "旧b")]
    new = [_src("b", "新b"), _src("c", "新c")]
    merged = merge_xhs_sources(existing, new)
    assert [s["note_id"] for s in merged] == ["a", "b", "c"]
    # 重复时保留先出现的 existing 记录
    assert next(s for s in merged if s["note_id"] == "b")["title"] == "旧b"


def test_merge_truncates_to_limit():
    new = [_src(str(i)) for i in range(10)]
    merged = merge_xhs_sources([], new, limit=3)
    assert [s["note_id"] for s in merged] == ["0", "1", "2"]


def test_merge_skips_records_without_note_id():
    new = [{"title": "无id"}, _src("a"), {"note_id": ""}]
    merged = merge_xhs_sources(None, new)
    assert [s["note_id"] for s in merged] == ["a"]


def test_merge_handles_none_inputs():
    assert merge_xhs_sources(None, None) == []


def test_merge_simulates_concurrent_step_writes():
    """模拟同一 step 内两个 tool 各写增量：reducer 被链式调用 (累积, 增量)。"""
    acc = []
    acc = merge_xhs_sources(acc, [_src("a"), _src("b")])
    acc = merge_xhs_sources(acc, [_src("b"), _src("c")])
    assert [s["note_id"] for s in acc] == ["a", "b", "c"]
