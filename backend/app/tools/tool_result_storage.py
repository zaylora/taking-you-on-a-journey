# -*- coding: utf-8 -*-
"""大工具结果落盘与分页读取。

用于避免单个 ToolMessage 把模型上下文撑爆：大结果写入后端本地文件，
模型上下文里只保留预览和 result_id。
"""
from pathlib import Path
from typing import Any
import json
import re
import uuid

_SAFE_PART_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def _safe_part(value: str, fallback: str) -> str:
    cleaned = _SAFE_PART_RE.sub("_", (value or "").strip()).strip("._")
    return cleaned[:80] or fallback


def _serialize_result(result: Any) -> str:
    return json.dumps(result, ensure_ascii=False, default=str)


def _write_result_file(text: str, *, tool_name: str, tool_call_id: str, storage_dir: str | Path) -> str:
    base_dir = Path(storage_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    safe_tool = _safe_part(tool_name, "tool")
    safe_call = _safe_part(tool_call_id, uuid.uuid4().hex[:12])
    result_id = f"{safe_tool}-{safe_call}.json"
    path = base_dir / result_id
    path.write_text(text, encoding="utf-8")
    return result_id


def maybe_persist_tool_result(
    result: Any,
    *,
    tool_name: str,
    tool_call_id: str = "",
    storage_dir: str | Path,
    threshold_chars: int,
    preview_chars: int,
) -> Any:
    """超过阈值时落盘，返回轻量 envelope；否则原样返回。"""
    text = _serialize_result(result)
    if len(text) <= threshold_chars:
        return result

    result_id = _write_result_file(
        text,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        storage_dir=storage_dir,
    )

    return {
        "ok": True,
        "persisted": True,
        "tool_name": tool_name,
        "result_id": result_id,
        "original_chars": len(text),
        "preview_chars": max(0, preview_chars),
        "preview": text[:max(0, preview_chars)],
        "hint": "完整工具结果已落盘；如确实需要原文，调用 read_persisted_tool_result 按 offset/limit 分页读取。",
    }


def persist_tool_content(
    content: Any,
    *,
    tool_name: str,
    tool_call_id: str,
    storage_dir: str | Path,
    threshold_chars: int,
    preview_chars: int,
) -> str | None:
    """content 归一化为文本；超阈值则落盘并返回 envelope JSON，否则返回 None。"""
    text = content if isinstance(content, str) else _serialize_result(content)
    if len(text) <= threshold_chars:
        return None

    result_id = _write_result_file(
        text,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        storage_dir=storage_dir,
    )
    return json.dumps({
        "ok": True,
        "persisted": True,
        "tool_name": tool_name,
        "result_id": result_id,
        "original_chars": len(text),
        "preview_chars": max(0, preview_chars),
        "preview": text[:max(0, preview_chars)],
        "hint": "完整工具结果已落盘；如需原文，调用 read_persisted_tool_result 按 offset/limit 分页读取。",
    }, ensure_ascii=False)


def _resolve_result_path(result_id: str, storage_dir: str | Path) -> Path | None:
    base = Path(storage_dir).resolve()
    candidate = (base / result_id).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    if candidate.name != result_id:
        return None
    return candidate


def read_persisted_tool_result_slice(
    result_id: str,
    *,
    offset: int,
    limit: int,
    storage_dir: str | Path,
) -> dict[str, Any]:
    """安全读取落盘结果的一段内容。"""
    path = _resolve_result_path(result_id, storage_dir)
    if path is None:
        return {"ok": False, "error": {"code": "invalid_result_id", "message": "result_id 不合法。"}}
    if not path.exists() or not path.is_file():
        return {"ok": False, "error": {"code": "not_found", "message": "未找到落盘工具结果。"}}

    text = path.read_text(encoding="utf-8")
    start = max(0, int(offset or 0))
    size = max(1, int(limit or 1))
    end = min(len(text), start + size)
    return {
        "ok": True,
        "result_id": result_id,
        "offset": start,
        "limit": size,
        "total_chars": len(text),
        "content": text[start:end],
        "has_more": end < len(text),
    }
