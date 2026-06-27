# -*- coding: utf-8 -*-
"""Read-only Xiaohongshu tools backed by jackwener/xiaohongshu-cli."""
import asyncio
import json
import os
import re
import shlex
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.llm.factory import build_llm
from app.agent.prompt import XHS_RESEARCH_SYS

_DEFAULT_TIMEOUT_SECONDS = 45
_SECRETISH_RE = re.compile(r"(?i)(a1|web_session|webId|xsecappid|cookie)[=:]\s*[^,\s;]+")
_NOTE_TEXT_LIMIT = 3500
_RESEARCH_NOTE_LIMIT = 6


def _redact_cli_text(text: str, *, limit: int = 1000) -> str:
    clipped = (text or "").strip()[:limit]
    return _SECRETISH_RE.sub(r"\1=<redacted>", clipped)


def _xhs_command(args: list[str]) -> list[str]:
    """Build a safe argv list. XHS_CLI_BIN may be 'xhs' or e.g. 'uv run xhs'."""
    base = shlex.split(os.getenv("XHS_CLI_BIN", "xhs"))
    return [*base, *args, "--json"]


def _xhs_timeout_seconds() -> float:
    raw = os.getenv("XHS_CLI_TIMEOUT_SECONDS", str(_DEFAULT_TIMEOUT_SECONDS))
    try:
        return max(5.0, float(raw))
    except ValueError:
        return float(_DEFAULT_TIMEOUT_SECONDS)


def _normalize_cli_result(returncode: int, stdout: bytes, stderr: bytes) -> dict[str, Any]:
    out_text = stdout.decode("utf-8", errors="replace").strip()
    err_text = stderr.decode("utf-8", errors="replace").strip()

    parsed: Any = None
    if out_text:
        try:
            parsed = json.loads(out_text)
        except json.JSONDecodeError:
            parsed = None

    if isinstance(parsed, dict):
        if returncode == 0:
            return parsed if "ok" in parsed else {"ok": True, "data": parsed}
        if parsed.get("ok") is False:
            return parsed

    if returncode == 0:
        return {"ok": True, "data": parsed if parsed is not None else out_text}

    message = _redact_cli_text(err_text or out_text or f"xhs exited with code {returncode}")
    return {
        "ok": False,
        "error": {
            "code": "xhs_cli_failed",
            "message": message,
            "hint": "先在后端运行 xhs status --json；如未登录，运行 xhs login --qrcode 完成扫码登录。",
        },
    }


async def _run_xhs_json(args: list[str]) -> dict[str, Any]:
    env = {**os.environ, "OUTPUT": "json"}
    try:
        proc = await asyncio.create_subprocess_exec(
            *_xhs_command(args),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "error": {
                "code": "xhs_cli_missing",
                "message": "未找到 xhs 命令。请先在 backend 执行 uv sync，或设置 XHS_CLI_BIN 指向可用的 xhs。",
            },
        }

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_xhs_timeout_seconds())
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        return {
            "ok": False,
            "error": {
                "code": "xhs_cli_timeout",
                "message": f"xhs 命令超过 {_xhs_timeout_seconds():.0f}s 未完成。",
            },
        }

    return _normalize_cli_result(proc.returncode, stdout, stderr)


def _walk_values(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_values(child)


def _first_string(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_note_targets(search_result: dict[str, Any], *, limit: int) -> list[str]:
    targets = []
    seen = set()
    for record in _walk_values(search_result.get("data", search_result)):
        if not isinstance(record, dict):
            continue
        target = _first_string(record, (
            "note_id", "noteId", "noteIdStr", "id", "note_url", "url",
            "share_url", "shareUrl", "link",
        ))
        if not target or target in seen:
            continue
        # Avoid grabbing obvious user/profile ids when richer note identifiers are absent.
        if target == record.get("user_id") or target == record.get("userId"):
            continue
        seen.add(target)
        targets.append(target)
        if len(targets) >= limit:
            break
    return targets


def _compact_json(value: Any, *, limit: int = _NOTE_TEXT_LIMIT) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text[:limit]


class XhsSearchNotesArgs(BaseModel):
    """Search Xiaohongshu notes."""

    keyword: str = Field(description="小红书搜索关键词，如 成都Citywalk、顺德美食、东京亲子游。")
    sort: Literal["general", "popular", "latest"] = Field(
        default="general",
        description="排序方式：general 综合、popular 最热、latest 最新。",
    )
    note_type: Literal["all", "video", "image"] = Field(
        default="all",
        description="内容类型过滤：all 全部、video 视频、image 图文。",
    )
    page: int = Field(default=1, ge=1, le=20, description="搜索页码，默认 1。")


class XhsReadTargetArgs(BaseModel):
    """Read a Xiaohongshu note-like target."""

    target: str = Field(
        description=(
            "笔记 ID、小红书笔记 URL，或最近一次 xhs 列表结果的短序号字符串。"
            "优先传完整 URL 或真实 note_id，不要编造。"
        )
    )


class XhsCommentsArgs(XhsReadTargetArgs):
    """Read note comments."""

    include_all: bool = Field(default=False, description="是否自动翻页拉取全部评论；大量评论会更慢。")


class XhsHotNotesArgs(BaseModel):
    """Browse hot Xiaohongshu notes."""

    category: Literal[
        "fashion", "food", "cosmetics", "movie", "career",
        "love", "home", "gaming", "travel", "fitness",
    ] = Field(default="travel", description="热门分类，旅行规划优先用 travel。")


class XhsUserProfileArgs(BaseModel):
    """Read a Xiaohongshu user profile."""

    user_id: str = Field(description="小红书用户 ID。")


class XhsTravelResearchArgs(BaseModel):
    """Research travel guide signals from Xiaohongshu notes."""

    city: str = Field(description="目的地城市或地区，如 顺德、成都、东京。")
    days: int = Field(default=1, ge=1, le=30, description="计划天数，用于判断攻略节奏。")
    travel_style: str = Field(
        default="",
        description="旅行偏好，如 亲子、情侣、citywalk、特种兵、松弛慢游、美食优先；未知可留空。",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="额外搜索关键词，如 避雷、拍照、夜市、雨天、带娃；可为空数组。",
    )
    max_notes: int = Field(default=4, ge=1, le=_RESEARCH_NOTE_LIMIT, description="最多读取的攻略笔记数。")
    include_comments: bool = Field(default=False, description="是否额外读取评论，用于挖掘避雷、排队和近期反馈。")


class XhsRecommendedPlace(BaseModel):
    name: str = Field(description="地点、店铺、街区或体验名称。")
    reason: str = Field(description="被推荐的原因，必须是归纳总结，不要长段复制原文。")
    priority: Literal["high", "medium", "low"] = Field(default="medium", description="参考优先级。")
    source_count: int = Field(default=1, ge=1, description="有多少来源提到或支撑。")


class XhsTimeSuggestion(BaseModel):
    time: str = Field(description="建议时间或时间段，如 09:00、上午、傍晚。")
    place: str = Field(description="适合该时间去的地点或区域。")
    activity: str = Field(description="该时间建议做什么。")
    reason: str = Field(description="时间建议背后的原因，如人少、顺光、避开排队。")


class XhsTravelBrief(BaseModel):
    city: str = Field(description="目的地。")
    summary: str = Field(description="攻略研究结论摘要。")
    recommended_places: list[XhsRecommendedPlace] = Field(default_factory=list)
    time_suggestions: list[XhsTimeSuggestion] = Field(default_factory=list)
    route_patterns: list[str] = Field(default_factory=list, description="常见顺路路线或半日/一日路线。")
    food_keywords: list[str] = Field(default_factory=list, description="值得继续用高德检索的美食/店铺关键词。")
    tips: list[str] = Field(default_factory=list, description="注意事项，如预约、排队、天气、拍照时间。")
    avoid_notes: list[str] = Field(default_factory=list, description="避雷或谨慎项，需归纳并避免绝对化。")
    amap_query_hints: list[str] = Field(default_factory=list, description="下一步建议交给高德检索的短关键词。")
    source_notes: list[dict[str, Any]] = Field(default_factory=list, description="简短来源索引，不含长原文。")


_XHS_RESEARCH_SYS = XHS_RESEARCH_SYS


@tool
async def xhs_status() -> dict[str, Any]:
    """检查后端本机 xiaohongshu-cli 登录状态。未登录时提示用户在后端运行 xhs login --qrcode。"""
    return await _run_xhs_json(["status"])


@tool(args_schema=XhsSearchNotesArgs)
async def xhs_search_notes(
    keyword: str,
    sort: Literal["general", "popular", "latest"] = "general",
    note_type: Literal["all", "video", "image"] = "all",
    page: int = 1,
) -> dict[str, Any]:
    """搜索小红书笔记，适合查旅行灵感、餐厅体验、路线反馈。返回 CLI 的结构化 envelope。"""
    return await _run_xhs_json([
        "search", keyword,
        "--sort", sort,
        "--type", note_type,
        "--page", str(page),
    ])


@tool(args_schema=XhsReadTargetArgs)
async def xhs_read_note(target: str) -> dict[str, Any]:
    """读取小红书笔记详情。target 应来自搜索结果、用户粘贴 URL 或真实 note_id。"""
    return await _run_xhs_json(["read", target])


@tool(args_schema=XhsCommentsArgs)
async def xhs_note_comments(target: str, include_all: bool = False) -> dict[str, Any]:
    """读取小红书笔记评论。需要大量评论分析时 include_all=true。"""
    args = ["comments", target]
    if include_all:
        args.append("--all")
    return await _run_xhs_json(args)


@tool(args_schema=XhsHotNotesArgs)
async def xhs_hot_notes(
    category: Literal[
        "fashion", "food", "cosmetics", "movie", "career",
        "love", "home", "gaming", "travel", "fitness",
    ] = "travel",
) -> dict[str, Any]:
    """浏览小红书热门笔记，默认旅行分类。"""
    return await _run_xhs_json(["hot", "-c", category])


@tool(args_schema=XhsUserProfileArgs)
async def xhs_user_profile(user_id: str) -> dict[str, Any]:
    """读取小红书用户主页资料。"""
    return await _run_xhs_json(["user", user_id])


@tool(args_schema=XhsTravelResearchArgs)
async def research_xhs_travel_guide(
    city: str,
    days: int = 1,
    travel_style: str = "",
    keywords: list[str] | None = None,
    max_notes: int = 4,
    include_comments: bool = False,
) -> dict[str, Any]:
    """研究小红书旅行攻略并提炼结构化参考。先用它学习攻略经验，再用高德工具校验 POI/天气/路线。"""
    keyword_parts = [f"{city}旅游攻略", f"{city}{days}日游", f"{city}美食"]
    if travel_style:
        keyword_parts.append(f"{city}{travel_style}")
    for keyword in keywords or []:
        if keyword and len(keyword_parts) < 6:
            keyword_parts.append(f"{city}{keyword}")

    searches = []
    targets = []
    seen_targets = set()
    for keyword in keyword_parts:
        result = await _run_xhs_json(["search", keyword, "--sort", "popular", "--type", "all", "--page", "1"])
        searches.append({"keyword": keyword, "result": result})
        if result.get("ok") is False:
            return result
        for target in _extract_note_targets(result, limit=max_notes):
            if target in seen_targets:
                continue
            seen_targets.add(target)
            targets.append(target)
            if len(targets) >= max_notes:
                break
        if len(targets) >= max_notes:
            break

    notes = []
    for target in targets[:max_notes]:
        note = await _run_xhs_json(["read", target])
        note_payload: dict[str, Any] = {"target": target, "note": note}
        if include_comments and note.get("ok") is not False:
            note_payload["comments"] = await _run_xhs_json(["comments", target])
        notes.append(note_payload)

    payload = {
        "city": city,
        "days": days,
        "travel_style": travel_style,
        "extra_keywords": keywords or [],
        "search_keywords": keyword_parts,
        "search_summaries": [
            {"keyword": item["keyword"], "result": _compact_json(item["result"], limit=1200)}
            for item in searches
        ],
        "notes": [
            {
                "target": item["target"],
                "note": _compact_json(item.get("note"), limit=_NOTE_TEXT_LIMIT),
                "comments": _compact_json(item.get("comments"), limit=1500) if "comments" in item else "",
            }
            for item in notes
        ],
    }

    llm = build_llm(temperature=0).with_structured_output(XhsTravelBrief, method="function_calling")
    brief = await llm.ainvoke([
        SystemMessage(content=_XHS_RESEARCH_SYS),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False, default=str)),
    ])
    brief_data = brief.model_dump() if isinstance(brief, BaseModel) else dict(brief)
    brief_data["source_notes"] = [
        {"target": item["target"], "ok": item.get("note", {}).get("ok", False)}
        for item in notes
    ]
    return {
        "ok": True,
        "data": brief_data,
        "meta": {
            "search_keywords": keyword_parts,
            "source_note_count": len(notes),
            "include_comments": include_comments,
        },
    }
