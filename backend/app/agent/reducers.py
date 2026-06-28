# -*- coding: utf-8 -*-
"""State channel reducers.

抽出 reducer 放独立模块，避免 state.py ↔ tools/xhs.py 循环导入。
"""
from typing import Any

XHS_SOURCE_LIMIT = 6


def merge_xhs_sources(
    existing: list[dict[str, Any]] | None,
    new_records: list[dict[str, Any]] | None,
    *,
    limit: int = XHS_SOURCE_LIMIT,
) -> list[dict[str, Any]]:
    """按 note_id 去重合并来源列表，保留先出现者，截断到 limit。

    作为 TripState.xhs_sources 的 reducer：同一 step 内多个 tool 各写增量时，
    LangGraph 会依次以 (累积值, 单次增量) 调用本函数完成合并，规避并发写冲突。
    """
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in [*(existing or []), *(new_records or [])]:
        note_id = (record or {}).get("note_id", "")
        if not note_id or note_id in seen:
            continue
        seen.add(note_id)
        merged.append(record)
        if len(merged) >= limit:
            break
    return merged
