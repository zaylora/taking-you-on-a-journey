# 小红书笔记来源链接 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成旅行攻略时，在回复结尾附上本次研究所用的小红书笔记来源链接（真实可点开、不经 LLM）。

**Architecture:** 在 `research_xhs_travel_guide` 搜索阶段采集 `{note_id, xsec_token, title, type, url}`，通过 `Command` 写入新增的 `TripState.xhs_sources`（跨轮累积、按 note_id 去重）。stream 层在模型流式结束后，从 state 取出来源，以 `## 笔记来源` markdown 列表补发 `token` 事件接到聊天气泡，并拼进 `final.answer`。

**Tech Stack:** Python 3 / LangGraph(create_agent) / LangChain tools(InjectedState, InjectedToolCallId, Command) / pytest / FastAPI SSE。

## Global Constraints

- 链接不经 LLM：来源 URL 必须在后端确定性拼接，不交给模型生成。
- 链接格式：优先 `https://www.xiaohongshu.com/explore/<id>?xsec_token=<token>&xsec_source=pc_search`；无 token 降级为 `https://www.xiaohongshu.com/explore/<id>`。
- 来源范围：仅 `research_xhs_travel_guide` 实际读取的笔记。
- 最多展示 6 条（对齐 `_RESEARCH_NOTE_LIMIT`）。
- 标题缺失兜底「小红书笔记」。
- 前端气泡正文来自流式 `token` 累积，不是 `final.answer`；追加必须补发 `token`。
- 仅本轮 `xhs_sources` 有新增时才追加，避免纯问答轮重复贴链接。
- 注释/命名沿用现有中文风格；工具改造后模型可见 schema 不得新增 injected 字段。
- 完成后在 `plan/YYYYMMDD_<任务简述>/README.md` 写改动记录（项目 CLAUDE.md 要求）。

---

### Task 1: TripState 增加 xhs_sources 字段

**Files:**
- Modify: `backend/app/agent/state.py:10-16`
- Test: `backend/tests/agent/test_state.py:4-7`

**Interfaces:**
- Produces: `TripState.xhs_sources: list` —— 元素为 `{"note_id": str, "xsec_token": str, "title": str, "type": str, "url": str}`。

- [ ] **Step 1: 改测试，断言新字段存在**

修改 [backend/tests/agent/test_state.py:6](../../../backend/tests/agent/test_state.py#L6) 的字段元组，加入 `"xhs_sources"`：

```python
def test_tripstate_has_business_fields():
    ann = TripState.__annotations__
    for field in ("day_plans", "changed_days", "plan_version", "budget_check", "retry_count", "summary", "xhs_sources"):
        assert field in ann, f"缺业务字段 {field}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/agent/test_state.py::test_tripstate_has_business_fields -v`
Expected: FAIL，AssertionError「缺业务字段 xhs_sources」

- [ ] **Step 3: 加字段**

在 [backend/app/agent/state.py](../../../backend/app/agent/state.py) 的 `TripState` 末尾加一行：

```python
class TripState(AgentState):
    day_plans: list
    changed_days: list
    plan_version: int
    budget_check: dict
    retry_count: int
    summary: str
    xhs_sources: list
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/agent/test_state.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/agent/state.py backend/tests/agent/test_state.py
git commit -m "feat(state): TripState 增加 xhs_sources 字段"
```

---

### Task 2: _build_note_url 拼接笔记链接

**Files:**
- Modify: `backend/app/agent/tools/xhs.py`（在常量区附近新增函数）
- Test: `backend/tests/agent/test_tools.py`（新增测试）

**Interfaces:**
- Produces: `_build_note_url(note_id: str, xsec_token: str = "") -> str`。`note_id` 为空返回 `""`；有 token 拼带 token 的 explore URL，否则拼裸 explore URL。

- [ ] **Step 1: 写失败测试**

在 [backend/tests/agent/test_tools.py](../../../backend/tests/agent/test_tools.py) 末尾追加：

```python
def test_build_note_url_with_token():
    url = xhs_tools._build_note_url("abc123", "TOKENXYZ")
    assert url == "https://www.xiaohongshu.com/explore/abc123?xsec_token=TOKENXYZ&xsec_source=pc_search"


def test_build_note_url_without_token_degrades():
    assert xhs_tools._build_note_url("abc123", "") == "https://www.xiaohongshu.com/explore/abc123"


def test_build_note_url_empty_id_returns_empty():
    assert xhs_tools._build_note_url("", "TOKEN") == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/agent/test_tools.py -k build_note_url -v`
Expected: FAIL，`AttributeError: module ... has no attribute '_build_note_url'`

- [ ] **Step 3: 实现函数**

在 [backend/app/agent/tools/xhs.py](../../../backend/app/agent/tools/xhs.py) 常量区之后（约 `_normalize_xhs_search_keyword` 附近）新增：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/agent/test_tools.py -k build_note_url -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/agent/tools/xhs.py backend/tests/agent/test_tools.py
git commit -m "feat(xhs): 新增 _build_note_url 拼接笔记链接"
```

---

### Task 3: _extract_source_records 从搜索结果提取来源记录

**Files:**
- Modify: `backend/app/agent/tools/xhs.py`（在 `_extract_note_targets` 之后新增）
- Test: `backend/tests/agent/test_tools.py`（新增测试）

**Interfaces:**
- Consumes: `_build_note_url`（Task 2）、`_walk_values`、`_first_string`（已存在）。
- Produces: `_extract_source_records(search_result: dict, *, limit: int) -> list[dict]`。返回 `[{"note_id", "xsec_token", "title", "type", "url"}, ...]`，按 note_id 去重，最多 `limit` 条。
  - note_id 取 item 级 `id`，回退 `note_id`/`noteId`。
  - xsec_token 取 item 级 `xsec_token`（笔记级，非 user 级）。
  - title 取 `note_card.display_title`，回退 `note_card.title`，缺失为 `""`。
  - type 取 `note_card.type`，缺失为 `""`。

- [ ] **Step 1: 写失败测试**

在 [backend/tests/agent/test_tools.py](../../../backend/tests/agent/test_tools.py) 末尾追加（贴近真实 CLI 结构：item 级 `id`+`xsec_token`，`note_card` 内含 `display_title`/`type`）：

```python
def test_extract_source_records_from_search_items():
    search_result = {
        "ok": True,
        "data": {
            "items": [
                {
                    "id": "6867e6f80000000017034699",
                    "xsec_token": "TOKEN_A",
                    "note_card": {"display_title": "顺德一日游", "type": "normal"},
                },
                {
                    "id": "68176d1e000000000303b562",
                    "xsec_token": "TOKEN_B",
                    "note_card": {"display_title": "", "type": "video"},
                },
            ]
        },
    }
    records = xhs_tools._extract_source_records(search_result, limit=6)
    assert records == [
        {
            "note_id": "6867e6f80000000017034699",
            "xsec_token": "TOKEN_A",
            "title": "顺德一日游",
            "type": "normal",
            "url": "https://www.xiaohongshu.com/explore/6867e6f80000000017034699?xsec_token=TOKEN_A&xsec_source=pc_search",
        },
        {
            "note_id": "68176d1e000000000303b562",
            "xsec_token": "TOKEN_B",
            "title": "",
            "type": "video",
            "url": "https://www.xiaohongshu.com/explore/68176d1e000000000303b562?xsec_token=TOKEN_B&xsec_source=pc_search",
        },
    ]


def test_extract_source_records_dedupes_and_limits():
    search_result = {
        "data": {
            "items": [
                {"id": "n1", "xsec_token": "t1", "note_card": {"display_title": "A", "type": "normal"}},
                {"id": "n1", "xsec_token": "t1", "note_card": {"display_title": "A", "type": "normal"}},
                {"id": "n2", "xsec_token": "t2", "note_card": {"display_title": "B", "type": "normal"}},
            ]
        }
    }
    records = xhs_tools._extract_source_records(search_result, limit=1)
    assert [r["note_id"] for r in records] == ["n1"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/agent/test_tools.py -k extract_source_records -v`
Expected: FAIL，`AttributeError: ... '_extract_source_records'`

- [ ] **Step 3: 实现函数**

在 [backend/app/agent/tools/xhs.py](../../../backend/app/agent/tools/xhs.py) 的 `_extract_note_targets`（约 256 行）之后新增。遍历 item 字典：凡含 `id` 或 `note_id` 的字典视为笔记 item，从其 `note_card` 取标题/类型：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/agent/test_tools.py -k extract_source_records -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/agent/tools/xhs.py backend/tests/agent/test_tools.py
git commit -m "feat(xhs): 新增 _extract_source_records 采集笔记来源"
```

---

### Task 4: research_xhs_travel_guide 写 state（返回 Command）

**Files:**
- Modify: `backend/app/agent/tools/xhs.py:539-636`
- Test: `backend/tests/agent/test_tools.py:343-484`（改两处现有测试 + 新增一例）

**Interfaces:**
- Consumes: `_extract_source_records`（Task 3）、`TripState.xhs_sources`（Task 1）。
- Produces: `research_xhs_travel_guide` 现在返回 `Command(update={"xhs_sources": [...], "messages": [ToolMessage(envelope_json, tool_call_id)]})`。envelope 与改造前结构一致（`{ok, data, meta}`）。`xhs_sources` = state 已有 + 本轮采集（按 note_id 去重，最多 `_RESEARCH_NOTE_LIMIT`），且只保留进入 `targets` 的笔记。

- [ ] **Step 1: 改造工具签名与返回**

修改 [backend/app/agent/tools/xhs.py](../../../backend/app/agent/tools/xhs.py)。先在文件顶部 imports 区补充（与 budget.py 一致）：

```python
from typing import Annotated, Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
```

把 `research_xhs_travel_guide`（约 539 行）改为采集来源 + 返回 Command。关键改动：(a) 签名加 `tool_call_id` / `state`；(b) 搜索循环里同步 `_extract_source_records`；(c) 末尾只保留 `targets` 内的来源、与 state 合并去重、返回 Command：

```python
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
    state: Annotated[dict, InjectedState] = None,
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
            return _research_command(tool_call_id, result, state, [])
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
    return _research_command(tool_call_id, envelope, state, read_sources)
```

- [ ] **Step 2: 新增 _research_command 合并去重辅助**

在 `research_xhs_travel_guide` 之前新增（与 state 已有 `xhs_sources` 按 note_id 合并去重，上限 `_RESEARCH_NOTE_LIMIT`）：

```python
def _merge_xhs_sources(
    existing: list[dict[str, Any]] | None,
    new_records: list[dict[str, Any]],
    *,
    limit: int = _RESEARCH_NOTE_LIMIT,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in [*(existing or []), *new_records]:
        note_id = (record or {}).get("note_id", "")
        if not note_id or note_id in seen:
            continue
        seen.add(note_id)
        merged.append(record)
        if len(merged) >= limit:
            break
    return merged


def _research_command(
    tool_call_id: str,
    envelope: dict[str, Any],
    state: dict[str, Any] | None,
    new_records: list[dict[str, Any]],
) -> Command:
    update: dict[str, Any] = {
        "messages": [ToolMessage(
            json.dumps(envelope, ensure_ascii=False, default=str),
            tool_call_id=tool_call_id,
        )],
    }
    if new_records:
        update["xhs_sources"] = _merge_xhs_sources(
            (state or {}).get("xhs_sources"), new_records,
        )
    return Command(update=update)
```

- [ ] **Step 3: 跑现有 research 测试，确认因返回类型变化而失败**

Run: `cd backend && uv run pytest tests/agent/test_tools.py -k research_xhs -v`
Expected: FAIL —— 旧断言用 `out["ok"]`/`out["data"]` 直接索引 Command，TypeError 或 KeyError。

- [ ] **Step 4: 改两处现有 research 测试为断言 Command + ToolMessage**

把 [test_research_xhs_travel_guide_extracts_structured_brief](../../../backend/tests/agent/test_tools.py#L343)（约 386-407 行）的调用与断言改为解析 Command 内的 envelope。注意 `_fake_run` 的 search 返回需带 item 级 `id`/`xsec_token`/`note_card` 才能采集到来源，故同步更新假数据：

```python
    async def _fake_run(args):
        calls.append(args)
        if args[0] == "search":
            return {"ok": True, "data": {"items": [
                {"id": "note-1", "xsec_token": "tok1", "model_type": "note",
                 "note_card": {"display_title": "顺德攻略一", "type": "normal"}},
                {"id": "note-2", "xsec_token": "tok2", "model_type": "note",
                 "note_card": {"display_title": "顺德攻略二", "type": "video"}},
            ]}}
        if args[0] == "read":
            return {"ok": True, "data": {"title": f"{args[1]} 攻略", "desc": "09:00 去清晖园，人少好拍"}}
        if args[0] == "comments":
            return {"ok": True, "data": {"comments": [{"content": "节假日排队久"}]}}
        return {"ok": True, "data": {}}
```

替换该测试的调用与断言段（约 386-407 行）为：

```python
    cmd = await tools.research_xhs_travel_guide.ainvoke({
        "type": "tool_call",
        "name": "research_xhs_travel_guide",
        "id": "call_r",
        "args": {
            "city": "顺德",
            "days": 1,
            "travel_style": "美食慢游",
            "keywords": ["避雷"],
            "max_notes": 2,
            "include_comments": True,
            "analyze_images": False,
            "state": {},
        },
    })

    from langgraph.types import Command as _Command
    assert isinstance(cmd, _Command)
    out = json.loads(cmd.update["messages"][0].content)
    assert out["ok"] is True
    assert out["data"]["recommended_places"][0]["name"] == "清晖园"
    assert out["data"]["time_suggestions"][0]["time"] == "09:00"
    assert out["data"]["amap_query_hints"] == ["清晖园", "华盖路步行街", "双皮奶"]
    assert out["meta"]["source_note_count"] == 2
    # 来源写回 state：两篇被读取的笔记
    assert [s["note_id"] for s in cmd.update["xhs_sources"]] == ["note-1", "note-2"]
    assert cmd.update["xhs_sources"][0]["url"].startswith(
        "https://www.xiaohongshu.com/explore/note-1?xsec_token=tok1")
    assert calls == [
        ["search", "顺德旅游攻略", "--sort", "popular", "--type", "all", "--page", "1"],
        ["read", "note-1"],
        ["comments", "note-1"],
        ["read", "note-2"],
        ["comments", "note-2"],
    ]
```

接着把 [test_research_xhs_travel_guide_includes_image_analysis_in_brief_payload](../../../backend/tests/agent/test_tools.py#L410) 末尾（约 468-484 行）的调用与断言改为解析 Command。其 `_fake_run` 的 search 返回也要带 item 级字段：

```python
    async def _fake_run(args):
        run_calls.append(args)
        if args[0] == "search":
            return {"ok": True, "data": {"items": [
                {"id": "note-1", "xsec_token": "tok1", "model_type": "note",
                 "note_card": {"display_title": "顺德旅游攻略", "type": "normal"}},
            ]}}
        if args[0] == "read":
            return {
                "ok": True,
                "data": {
                    "items": [{
                        "note_card": {
                            "title": "顺德旅游攻略",
                            "desc": "正文提到清晖园。",
                            "image_list": [{"url_default": "https://sns-img-qc.xhscdn.com/a.jpg"}],
                        }
                    }]
                },
            }
        return {"ok": True, "data": {}}
```

替换该测试末尾调用与断言（约 468-484 行）为：

```python
    cmd = await tools.research_xhs_travel_guide.ainvoke({
        "type": "tool_call",
        "name": "research_xhs_travel_guide",
        "id": "call_r2",
        "args": {
            "city": "顺德",
            "days": 1,
            "travel_style": "",
            "keywords": [],
            "max_notes": 1,
            "include_comments": False,
            "analyze_images": True,
            "max_images_per_note": 1,
            "state": {},
        },
    })

    from langgraph.types import Command as _Command
    assert isinstance(cmd, _Command)
    out = json.loads(cmd.update["messages"][0].content)
    payload = json.loads(llm_calls[0][1].content)
    assert payload["notes"][0]["image_analysis"]["places"] == ["清晖园"]
    assert payload["notes"][0]["image_analysis"]["foods"] == ["双皮奶"]
    assert out["data"]["visual_clues"] == ["图片文字显示清晖园 09:00"]
    assert out["meta"]["image_analysis_count"] == 1
    assert [s["note_id"] for s in cmd.update["xhs_sources"]] == ["note-1"]
    assert run_calls[0] == ["search", "顺德旅游攻略", "--sort", "popular", "--type", "all", "--page", "1"]
```

- [ ] **Step 5: 新增「与 state 已有来源合并去重」测试**

在 [backend/tests/agent/test_tools.py](../../../backend/tests/agent/test_tools.py) 末尾追加：

```python
@pytest.mark.asyncio
async def test_research_xhs_merges_with_existing_state_sources(monkeypatch):
    async def _fake_run(args):
        if args[0] == "search":
            return {"ok": True, "data": {"items": [
                {"id": "note-1", "xsec_token": "tok1", "model_type": "note",
                 "note_card": {"display_title": "新攻略", "type": "normal"}},
            ]}}
        if args[0] == "read":
            return {"ok": True, "data": {"title": "新攻略", "desc": "正文"}}
        return {"ok": True, "data": {}}

    brief = xhs_tools.XhsTravelBrief(city="顺德", summary="略")
    monkeypatch.setattr(xhs_tools, "_run_xhs_json", _fake_run)
    monkeypatch.setattr(xhs_tools, "build_llm", make_fake_build_llm(structured=brief))

    cmd = await tools.research_xhs_travel_guide.ainvoke({
        "type": "tool_call",
        "name": "research_xhs_travel_guide",
        "id": "call_r3",
        "args": {
            "city": "顺德", "days": 1, "max_notes": 1, "analyze_images": False,
            "state": {"xhs_sources": [
                {"note_id": "note-0", "xsec_token": "t0", "title": "旧", "type": "normal",
                 "url": "https://www.xiaohongshu.com/explore/note-0?xsec_token=t0&xsec_source=pc_search"},
            ]},
        },
    })

    from langgraph.types import Command as _Command
    assert isinstance(cmd, _Command)
    # 旧来源保留 + 新来源追加，按 note_id 去重
    assert [s["note_id"] for s in cmd.update["xhs_sources"]] == ["note-0", "note-1"]
```

- [ ] **Step 6: 跑全部 research 测试确认通过**

Run: `cd backend && uv run pytest tests/agent/test_tools.py -k "research_xhs or build_note_url or extract_source_records" -v`
Expected: PASS（含 Task 2/3/4 全部用例）

- [ ] **Step 7: 提交**

```bash
git add backend/app/agent/tools/xhs.py backend/tests/agent/test_tools.py
git commit -m "feat(xhs): research_xhs_travel_guide 采集来源并写回 state"
```

---

### Task 5: stream 层结尾追加笔记来源

**Files:**
- Modify: `backend/app/graph/stream.py`
- Test: `backend/tests/test_chat_stream.py`（新增 render 纯函数测试）

**Interfaces:**
- Consumes: `TripState.xhs_sources`（Task 1/4 写入）。
- Produces: `render_xhs_sources(sources: list[dict], *, limit: int = 6) -> str`。返回 `\n\n## 笔记来源\n- [标题](url)\n...`；空列表返回 `""`；标题缺失用「小红书笔记」兜底；跳过无 url 的记录。
- sse_events 行为：模型流式结束后，若本轮 `xhs_sources` 较进入前有新增且 answer 非空，则按 `render_xhs_sources` 结果补发 `EVENT_TOKEN`，并把该段拼进 `final.answer`。

- [ ] **Step 1: 写 render 纯函数失败测试**

在 [backend/tests/test_chat_stream.py](../../../backend/tests/test_chat_stream.py) 末尾追加：

```python
from app.graph.stream import render_xhs_sources


def test_render_xhs_sources_basic():
    md = render_xhs_sources([
        {"title": "顺德一日游", "url": "https://www.xiaohongshu.com/explore/n1?xsec_token=t1&xsec_source=pc_search"},
        {"title": "", "url": "https://www.xiaohongshu.com/explore/n2"},
    ])
    assert md.startswith("\n\n## 笔记来源\n")
    assert "- [顺德一日游](https://www.xiaohongshu.com/explore/n1?xsec_token=t1&xsec_source=pc_search)" in md
    assert "- [小红书笔记](https://www.xiaohongshu.com/explore/n2)" in md


def test_render_xhs_sources_empty_returns_blank():
    assert render_xhs_sources([]) == ""


def test_render_xhs_sources_skips_missing_url_and_limits():
    md = render_xhs_sources(
        [
            {"title": "A", "url": "https://x/1"},
            {"title": "B", "url": ""},
            {"title": "C", "url": "https://x/3"},
        ],
        limit=1,
    )
    assert "[A](https://x/1)" in md
    assert "B" not in md  # 无 url 跳过
    assert "C" not in md  # 超过 limit
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_chat_stream.py -k render_xhs_sources -v`
Expected: FAIL，`ImportError: cannot import name 'render_xhs_sources'`

- [ ] **Step 3: 实现 render_xhs_sources**

在 [backend/app/graph/stream.py](../../../backend/app/graph/stream.py) 的 `_as_text` 之后新增：

```python
_XHS_SOURCE_LIMIT = 6
_XHS_SOURCE_FALLBACK_TITLE = "小红书笔记"


def render_xhs_sources(sources: list[dict], *, limit: int = _XHS_SOURCE_LIMIT) -> str:
    """把 xhs_sources 渲染成 markdown「## 笔记来源」列表。空或全无 url 时返回空串。"""
    lines = []
    for src in sources or []:
        url = (src.get("url") or "").strip()
        if not url:
            continue
        title = (src.get("title") or "").strip() or _XHS_SOURCE_FALLBACK_TITLE
        lines.append(f"- [{title}]({url})")
        if len(lines) >= limit:
            break
    if not lines:
        return ""
    return "\n\n## 笔记来源\n" + "\n".join(lines)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_chat_stream.py -k render_xhs_sources -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 接入 sse_events（补发 token + 拼 final.answer）**

修改 [backend/app/graph/stream.py](../../../backend/app/graph/stream.py) 的 `sse_events`。在开始流式前，为已有会话抓取进入前的来源数量基线（新会话为 0）；在生成 `final` 前比较并追加。

(a) 在 `stream_input = ...` 之后、`async for ev in graph.astream_events(...)` 之前插入基线抓取：

```python
        prior_state = await graph.aget_state(config)
        prior_source_count = len((prior_state.values or {}).get("xhs_sources", []) or [])
```

(b) 在 `answer = ...` 求出后、构造 `EVENT_FINAL` 之前插入追加逻辑（紧接 [stream.py:88](../../../backend/app/graph/stream.py#L88) 的 `day_plans = ...` 之前或之后均可，建议放在 answer 计算后）：

```python
        xhs_sources = values.get("xhs_sources", []) or []
        if answer and len(xhs_sources) > prior_source_count:
            sources_md = render_xhs_sources(xhs_sources)
            if sources_md:
                yield _sse(EVENT_TOKEN, {"text": sources_md})
                answer = answer + sources_md
```

(c) `EVENT_FINAL` 的 `answer` 字段已是更新后的 `answer`，无需再改。

- [ ] **Step 6: 跑 stream 全部测试 + 全量回归**

Run: `cd backend && uv run pytest tests/test_chat_stream.py -v && uv run pytest -q`
Expected: PASS（stream 测试全绿；全量无新增失败）

- [ ] **Step 7: 提交**

```bash
git add backend/app/graph/stream.py backend/tests/test_chat_stream.py
git commit -m "feat(stream): 攻略结尾追加小红书笔记来源链接"
```

---

### Task 6: 系统提示提示来源行为 + 改动记录

**Files:**
- Modify: `backend/app/agent/prompt.py:36-38`（回复要求段，可选微调）
- Create: `plan/20260628_xhs_source_links/README.md`

**Interfaces:**
- 无新接口。仅文档与提示文案。

- [ ] **Step 1: 提示文案微调（让模型知道来源由系统追加，不要自己编链接）**

在 [backend/app/agent/prompt.py](../../../backend/app/agent/prompt.py) 的「## 回复要求」段末尾补一句：

```python
## 回复要求
用简体中文回复。规划/修改场景写清晰的逐日攻略；推荐场景给出可执行的分组建议，说明哪些来自口碑经验、哪些已被地图 POI 校验；问答场景直接回答。语气友好实用，避免暴露内部推理过程。

小红书笔记来源链接由系统在回复结尾自动附上，你不要自己编造或重复粘贴笔记 URL。
```

- [ ] **Step 2: 跑 prompt 相关测试确认未破坏**

Run: `cd backend && uv run pytest tests/agent/test_prompt.py -v`
Expected: PASS（若该测试断言提示内容，按需同步；否则全绿）

- [ ] **Step 3: 写改动记录**

创建 `plan/20260628_xhs_source_links/README.md`，包含：任务目标、改动文件清单（state.py / xhs.py / stream.py / prompt.py / 三处测试）、改动详情（搜索阶段采集 id+xsec_token、Command 写 state、stream 补发 token）、测试结果（贴 `uv run pytest -q` 结果摘要）、相关讨论（笔记级 vs 用户级 xsec_token 的关键区别）。

- [ ] **Step 4: 提交**

```bash
git add backend/app/agent/prompt.py plan/20260628_xhs_source_links/README.md
git commit -m "docs(xhs): 提示来源由系统追加 + 改动记录"
```

---

## Self-Review

**Spec coverage:**
- 数据流三段（搜索采集 / Command 写 state / 结尾追加）→ Task 3、Task 4、Task 5 ✓
- 关键约束「前端正文来自流式 token」→ Task 5 Step 5 补发 token ✓
- `_build_note_url` 优先完整 URL 降级 → Task 2 ✓
- `_extract_source_records` → Task 3 ✓
- `TripState.xhs_sources` → Task 1 ✓
- 跨轮累积去重 → Task 4 `_merge_xhs_sources` + Task 4 Step 5 测试 ✓
- 仅本轮有新增才追加 → Task 5 Step 5 `len(xhs_sources) > prior_source_count` ✓
- 标题缺失兜底 / 数量上限 6 → Task 5 `render_xhs_sources` ✓
- 边界：CLI 失败仍返回 Command 不更新 sources → Task 4 `_research_command`（search 失败分支传 `[]`）✓
- 测试：build_note_url / extract / research Command / stream render → Task 2-5 ✓
- 现有返回 dict 的 research 测试同步改 Command → Task 4 Step 4 ✓

**Placeholder scan:** 无 TBD/TODO；每个代码步骤含完整代码。Task 6 Step 3 的 README 内容为文档描述（非代码），可接受。

**Type consistency:** `_build_note_url(note_id, xsec_token)`、`_extract_source_records(search_result, *, limit)`、`_merge_xhs_sources(existing, new_records, *, limit)`、`_research_command(tool_call_id, envelope, state, new_records)`、`render_xhs_sources(sources, *, limit)` —— 跨任务签名一致。来源记录字段 `{note_id, xsec_token, title, type, url}` 全程统一。
