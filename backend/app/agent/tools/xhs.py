# -*- coding: utf-8 -*-
"""Read-only Xiaohongshu tools backed by jackwener/xiaohongshu-cli."""
import asyncio
import json
import os
import re
import shlex
from typing import Annotated, Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.llm.factory import build_llm
from app.agent.prompt import XHS_RESEARCH_SYS

_DEFAULT_TIMEOUT_SECONDS = 45
_SECRETISH_RE = re.compile(r"(?i)(a1|web_session|webId|xsecappid|cookie)[=:]\s*[^,\s;]+")
_NOTE_TEXT_LIMIT = 3500
_RESEARCH_NOTE_LIMIT = 6
_GUIDE_KEYWORD_LIMIT = 6
_TRAVEL_SEARCH_MARKERS = (
    "旅游", "旅行", "游玩", "亲子", "情侣", "citywalk", "Citywalk",
    "美食", "餐厅", "小吃", "甜品", "咖啡", "景点", "路线",
    "避雷", "拍照", "雨天", "夜市",
)
_IMAGE_CONTAINER_KEYS = {
    "image", "images", "image_list", "imageinfo", "image_info",
    "cover", "cover_image", "coverimage",
}
_IMAGE_URL_KEYS = {"url", "url_default", "url_pre", "src", "href"}
_NON_NOTE_IMAGE_HINTS = ("avatar", "profile", "icon", "emoji")
_XHS_EXPLORE_BASE = "https://www.xiaohongshu.com/explore/"


def _build_note_url(note_id: str, xsec_token: str = "") -> str:
    """拼小红书笔记 URL。有 xsec_token 时拼可直接点开的完整链接，否则降级为裸 explore 链接。"""
    nid = (note_id or "").strip()
    if not nid:
        return ""
    token = (xsec_token or "").strip()
    if token:
        return f"{_XHS_EXPLORE_BASE}{nid}?xsec_token={token}&xsec_source=pc_search"
    return f"{_XHS_EXPLORE_BASE}{nid}"


_XHS_IMAGE_SYS = """# 小红书图文解析

## 角色
你是小红书旅行图文解析助手。你会结合笔记正文和图片，提取图片中可见的文字、地点、店名、菜单、价格、时间、路线和避雷线索。

## 约束
- 只提取图片和正文能支持的信息，不要凭常识补全。
- 忽略头像、水印、表情和无关装饰图。
- 看不清或不确定时把 confidence 设为 low，并在 warnings 中说明。
- 输出短句，适合后续旅行研究摘要归纳和高德检索。
"""


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


def _clean_xhs_keyword(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip())


def _ensure_xhs_guide_keyword(city: str, phrase: str = "") -> str:
    city_clean = _clean_xhs_keyword(city)
    phrase_clean = _clean_xhs_keyword(phrase)
    if not city_clean:
        return phrase_clean if "攻略" in phrase_clean else f"{phrase_clean}攻略"
    if not phrase_clean:
        return f"{city_clean}旅游攻略"
    base = phrase_clean if phrase_clean.startswith(city_clean) else f"{city_clean}{phrase_clean}"
    return base if "攻略" in base else f"{base}攻略"


def _build_xhs_guide_keywords(
    city: str,
    days: int,
    travel_style: str,
    keywords: list[str] | None,
    *,
    limit: int = _GUIDE_KEYWORD_LIMIT,
) -> list[str]:
    raw_phrases = ["旅游攻略", f"{days}日游攻略", "美食攻略"]
    if travel_style:
        raw_phrases.append(f"{_clean_xhs_keyword(travel_style)}攻略")
    for keyword in keywords or []:
        cleaned = _clean_xhs_keyword(keyword)
        if cleaned:
            raw_phrases.append(cleaned if "攻略" in cleaned else f"{cleaned}攻略")

    out: list[str] = []
    seen: set[str] = set()
    for phrase in raw_phrases:
        keyword = _ensure_xhs_guide_keyword(city, phrase)
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        out.append(keyword)
        if len(out) >= limit:
            break
    return out


def _normalize_xhs_search_keyword(keyword: str) -> str:
    cleaned = _clean_xhs_keyword(keyword)
    if not cleaned or "攻略" in cleaned:
        return cleaned
    if any(marker in cleaned for marker in _TRAVEL_SEARCH_MARKERS):
        return f"{cleaned}攻略"
    return cleaned


def _is_xhs_image_url(value: str) -> bool:
    text = value.strip()
    if not text.lower().startswith(("http://", "https://")):
        return False
    lowered = text.lower()
    if any(hint in lowered for hint in _NON_NOTE_IMAGE_HINTS):
        return False
    if lowered.endswith((".mp4", ".mov", ".m3u8")):
        return False
    return True


def _extract_xhs_image_urls(value: Any, *, limit: int = 4) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def add_url(raw: str) -> None:
        if len(urls) >= limit:
            return
        cleaned = raw.strip()
        if not _is_xhs_image_url(cleaned) or cleaned in seen:
            return
        seen.add(cleaned)
        urls.append(cleaned)

    def walk(node: Any, *, in_image_container: bool = False) -> None:
        if len(urls) >= limit:
            return
        if isinstance(node, str):
            if in_image_container:
                add_url(node)
            return
        if isinstance(node, dict):
            for key, child in node.items():
                key_l = str(key).lower()
                next_in_image = (
                    in_image_container
                    or key_l in _IMAGE_CONTAINER_KEYS
                    or "image_list" in key_l
                    or "cover" in key_l
                )
                if next_in_image and key_l in _IMAGE_URL_KEYS and isinstance(child, str):
                    add_url(child)
                walk(child, in_image_container=next_in_image)
        elif isinstance(node, list):
            for child in node:
                walk(child, in_image_container=in_image_container)
                if len(urls) >= limit:
                    break

    walk(value)
    return urls


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


def _extract_source_records(search_result: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    """从搜索结果提取笔记级来源记录，按 note_id 去重。

    笔记级 xsec_token 只在搜索结果 item 级出现（read 阶段拿到的是 user 级 token），
    所以必须在搜索阶段采集 id + xsec_token + 标题。
    """
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in _walk_values(search_result.get("data", search_result)):
        if not isinstance(record, dict):
            continue
        note_id = _first_string(record, ("id", "note_id", "noteId", "noteIdStr"))
        if not note_id or note_id in seen:
            continue
        # 排除明显的用户 id：item 同时带 model_type=note 或含 note_card 才算笔记
        note_card = record.get("note_card")
        if not isinstance(note_card, dict) and record.get("model_type") != "note":
            continue
        seen.add(note_id)
        card = note_card if isinstance(note_card, dict) else {}
        title = _first_string(card, ("display_title", "title"))
        note_type = _first_string(card, ("type",))
        xsec_token = _first_string(record, ("xsec_token", "xsecToken"))
        records.append({
            "note_id": note_id,
            "xsec_token": xsec_token,
            "title": title,
            "type": note_type,
            "url": _build_note_url(note_id, xsec_token),
        })
        if len(records) >= limit:
            break
    return records


def _compact_json(value: Any, *, limit: int = _NOTE_TEXT_LIMIT) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text[:limit]


class XhsSearchNotesArgs(BaseModel):
    """Search Xiaohongshu notes."""

    keyword: str = Field(
        description=(
            "小红书搜索关键词。旅行场景优先用攻略型描述，如 顺德旅游攻略、东京亲子游攻略、"
            "成都Citywalk攻略；工具会尽量为旅行关键词补齐“攻略”。"
        )
    )
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


class XhsReadNoteArgs(XhsReadTargetArgs):
    """Read a Xiaohongshu note and optionally analyze images."""

    analyze_images: bool = Field(
        default=True,
        description="是否用多模态 LLM 解析笔记图片，默认开启以覆盖图文攻略中的图片信息。",
    )
    max_images: int = Field(default=4, ge=0, le=6, description="最多解析多少张笔记图片。")


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


class XhsVisualBrief(BaseModel):
    target: str = Field(description="笔记目标 ID 或 URL。")
    image_count: int = Field(default=0, ge=0, description="实际送入视觉模型的图片数量。")
    visible_text: list[str] = Field(default_factory=list, description="图片中可见的短文字，如店名、菜单、价格、营业时间。")
    places: list[str] = Field(default_factory=list, description="图片或正文能支持的地点、店铺、街区名称。")
    foods: list[str] = Field(default_factory=list, description="图片或正文能支持的菜品、小吃、饮品关键词。")
    route_or_time_clues: list[str] = Field(default_factory=list, description="图片中出现的路线、时间段、排队或预约线索。")
    tips: list[str] = Field(default_factory=list, description="可用于攻略的注意事项。")
    confidence: Literal["high", "medium", "low"] = Field(default="medium", description="整体视觉解析置信度。")
    warnings: list[str] = Field(default_factory=list, description="解析限制或失败原因。")
    image_urls: list[str] = Field(default_factory=list, description="参与解析的图片 URL。")


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
    analyze_images: bool = Field(default=True, description="是否解析攻略笔记中的图片信息。")
    max_images_per_note: int = Field(default=4, ge=0, le=6, description="每篇笔记最多解析多少张图片。")


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
    visual_clues: list[str] = Field(default_factory=list, description="从图片解析得到、仍需地图或正文校验的短线索。")
    tips: list[str] = Field(default_factory=list, description="注意事项，如预约、排队、天气、拍照时间。")
    avoid_notes: list[str] = Field(default_factory=list, description="避雷或谨慎项，需归纳并避免绝对化。")
    amap_query_hints: list[str] = Field(default_factory=list, description="下一步建议交给高德检索的短关键词。")
    source_notes: list[dict[str, Any]] = Field(default_factory=list, description="简短来源索引，不含长原文。")


_XHS_RESEARCH_SYS = XHS_RESEARCH_SYS


def _build_xhs_image_messages(
    target: str,
    note: dict[str, Any],
    image_urls: list[str],
) -> list[SystemMessage | HumanMessage]:
    note_text = _compact_json(note, limit=1800)
    blocks: list[dict[str, Any]] = [{
        "type": "text",
        "text": (
            "请解析这篇小红书旅行笔记的图文信息。"
            f"\n目标: {target}"
            f"\n笔记JSON摘要: {note_text}"
            "\n重点提取图片中出现的地点、店名、菜单、价格、营业时间、路线、排队和避雷线索。"
        ),
    }]
    for url in image_urls:
        blocks.append({"type": "image_url", "image_url": {"url": url}})
    return [
        SystemMessage(content=_XHS_IMAGE_SYS),
        HumanMessage(content=blocks),
    ]


async def _analyze_xhs_note_images(
    target: str,
    note: dict[str, Any],
    *,
    max_images: int = 4,
) -> dict[str, Any]:
    image_urls = _extract_xhs_image_urls(note, limit=max(0, min(max_images, 6)))
    if not image_urls:
        return XhsVisualBrief(
            target=target,
            image_count=0,
            confidence="low",
            warnings=["xhs_note_has_no_extractable_images"],
            image_urls=[],
        ).model_dump()

    try:
        llm = build_llm(temperature=0, disable_streaming=True).with_structured_output(
            XhsVisualBrief,
            method="function_calling",
        )
        result = await llm.ainvoke(_build_xhs_image_messages(target, note, image_urls))
        data = result.model_dump() if isinstance(result, BaseModel) else dict(result)
        data["target"] = data.get("target") or target
        data["image_count"] = len(image_urls)
        data["image_urls"] = image_urls
        return data
    except Exception:
        return XhsVisualBrief(
            target=target,
            image_count=len(image_urls),
            confidence="low",
            warnings=["xhs_image_analysis_failed"],
            image_urls=image_urls,
        ).model_dump()


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
    search_keyword = _normalize_xhs_search_keyword(keyword)
    return await _run_xhs_json([
        "search", search_keyword,
        "--sort", sort,
        "--type", note_type,
        "--page", str(page),
    ])


@tool(args_schema=XhsReadNoteArgs)
async def xhs_read_note(
    target: str,
    analyze_images: bool = True,
    max_images: int = 4,
) -> dict[str, Any]:
    """读取小红书笔记详情。默认额外解析图文笔记中的图片信息，target 应来自搜索结果、用户粘贴 URL 或真实 note_id。"""
    result = await _run_xhs_json(["read", target])
    if analyze_images and max_images > 0 and result.get("ok") is not False:
        analysis = await _analyze_xhs_note_images(target, result, max_images=max_images)
        result = dict(result)
        result["image_analysis"] = analysis
        meta = dict(result.get("meta") or {})
        meta["image_analysis"] = {
            "attempted": True,
            "image_count": int(analysis.get("image_count", 0)),
            "warnings": list(analysis.get("warnings", [])),
        }
        result["meta"] = meta
    return result


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


def _research_command(
    tool_call_id: str,
    envelope: dict[str, Any],
    new_records: list[dict[str, Any]],
) -> Command:
    update: dict[str, Any] = {
        "messages": [ToolMessage(
            json.dumps(envelope, ensure_ascii=False, default=str),
            tool_call_id=tool_call_id,
        )],
    }
    # 只写本轮增量，合并/去重/截断交给 TripState.xhs_sources 的 reducer，
    # 这样同一 step 多个 research tool 并行写入不会触发 LastValue 并发写冲突。
    if new_records:
        update["xhs_sources"] = new_records
    return Command(update=update)


@tool(args_schema=XhsTravelResearchArgs)
async def research_xhs_travel_guide(
    city: str,
    days: int = 1,
    travel_style: str = "",
    keywords: list[str] | None = None,
    max_notes: int = 4,
    include_comments: bool = False,
    analyze_images: bool = True,
    max_images_per_note: int = 4,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """研究小红书旅行攻略并提炼结构化参考。先用它学习攻略经验，再用高德工具校验 POI/天气/路线。
    采集到的笔记来源链接会写回 state，最终回复结尾会自动附上来源。"""
    keyword_parts = _build_xhs_guide_keywords(
        city=city,
        days=days,
        travel_style=travel_style,
        keywords=keywords or [],
    )

    searches = []
    targets = []
    seen_targets = set()
    source_by_id: dict[str, dict[str, Any]] = {}
    for keyword in keyword_parts:
        result = await _run_xhs_json(["search", keyword, "--sort", "popular", "--type", "all", "--page", "1"])
        searches.append({"keyword": keyword, "result": result})
        if result.get("ok") is False:
            return _research_command(tool_call_id, result, [])
        for record in _extract_source_records(result, limit=max_notes):
            source_by_id.setdefault(record["note_id"], record)
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
    image_analysis_count = 0
    for target in targets[:max_notes]:
        note = await _run_xhs_json(["read", target])
        note_payload: dict[str, Any] = {"target": target, "note": note}
        if analyze_images and max_images_per_note > 0 and note.get("ok") is not False:
            image_analysis = await _analyze_xhs_note_images(
                target,
                note,
                max_images=max_images_per_note,
            )
            note_payload["image_analysis"] = image_analysis
            if image_analysis.get("image_count", 0):
                image_analysis_count += 1
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
                "image_analysis": item.get("image_analysis", {}),
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

    # 只保留实际被读取的笔记来源（targets 对齐）
    read_sources = [source_by_id[t] for t in targets[:max_notes] if t in source_by_id]
    envelope = {
        "ok": True,
        "data": brief_data,
        "meta": {
            "search_keywords": keyword_parts,
            "source_note_count": len(notes),
            "include_comments": include_comments,
            "analyze_images": analyze_images,
            "image_analysis_count": image_analysis_count,
            "max_images_per_note": max_images_per_note,
            "source_link_count": len(read_sources),
        },
    }
    return _research_command(tool_call_id, envelope, read_sources)
