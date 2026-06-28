# Dynamic Tool Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace raw/static tool progress labels with dynamic Chinese labels derived from each tool call's arguments.

**Architecture:** Add a focused backend formatter in `app.services.tool_labels`, then call it from the SSE bridge and graph-history aggregation. The frontend remains display-only and continues to render the `label` field already present in `tool_call`, `tool_result`, and persisted `tool_steps`.

**Tech Stack:** Python 3.12, FastAPI, LangGraph `astream_events`, pytest.

## Global Constraints

- Tool progress labels must not expose internal snake_case tool names to users.
- Do not add an LLM call for progress labels; these labels must appear immediately when the tool starts.
- Keep SSE event names and payload shape unchanged: `{"tool","label"}`.
- Record the completed change under `plan/YYYYMMDD_<任务简述>/README.md`.

---

### Task 1: Dynamic Label Formatter

**Files:**
- Create: `backend/app/services/tool_labels.py`
- Test: `backend/tests/test_tool_labels.py`

**Interfaces:**
- Produces: `build_tool_label(name: str | None, args: Mapping[str, Any] | None = None) -> str`

- [x] **Step 1: Write the failing test**

```python
from app.services.tool_labels import build_tool_label


def test_research_xhs_travel_guide_label_uses_city_days_and_keywords():
    assert build_tool_label(
        "research_xhs_travel_guide",
        {"city": "顺德", "days": 2, "travel_style": "亲子", "keywords": ["早茶", "清晖园"]},
    ) == "研究顺德2天亲子小红书攻略：早茶、清晖园"
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_tool_labels.py -q`

Expected before implementation: `ModuleNotFoundError: No module named 'app.services.tool_labels'`

- [x] **Step 3: Write minimal implementation**

Create `build_tool_label` with deterministic formatters for xhs, 高德搜索、天气、路线、行程、住宿、预算、确认行程 and a safe unknown-tool fallback.

- [x] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_tool_labels.py -q`

Expected: `4 passed`

### Task 2: Wire Dynamic Labels Into Realtime SSE

**Files:**
- Modify: `backend/app/graph/stream.py`
- Test: `backend/tests/test_chat_stream.py`

**Interfaces:**
- Consumes: `build_tool_label(name, args)`
- Uses LangChain event input: `event["data"]["input"]`

- [x] **Step 1: Write the failing stream test**

Use a fake `on_tool_start` event with `data.input={"city":"顺德","days":1,"travel_style":"美食"}` and assert both `tool_call` SSE and persisted `tool_steps` label equal `研究顺德1天美食小红书攻略`.

- [x] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_chat_stream.py::test_sse_events_persists_ui_history_matching_realtime_stream -q`

Expected before implementation: persisted label is `research_xhs_travel_guide`.

- [x] **Step 3: Implement stream wiring**

Extract tool input from event data, build one label at `on_tool_start`, store it in `tool_steps`, and reuse the stored label for matching `on_tool_end`.

- [x] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_chat_stream.py::test_sse_events_persists_ui_history_matching_realtime_stream -q`

Expected: `1 passed`

### Task 3: Wire Dynamic Labels Into History Replay

**Files:**
- Modify: `backend/app/services/message_history.py`
- Test: `backend/tests/test_session_aggregate.py`

**Interfaces:**
- Consumes: `build_tool_label(tc.get("name"), tc.get("args") or {})`

- [x] **Step 1: Write the failing aggregation test**

Create an `AIMessage` with tool calls containing args for `research_xhs_travel_guide` and `search_restaurants`; assert aggregated `tool_steps[].label` includes city/style/keyword context.

- [x] **Step 2: Implement history wiring**

Replace `TOOL_LABELS.get(...)` in `tool_steps()` with `build_tool_label(...)`.

- [x] **Step 3: Run focused tests**

Run: `cd backend && uv run pytest tests/test_tool_labels.py tests/test_chat_stream.py tests/test_session_aggregate.py tests/test_sessions.py -q`

Expected: focused tests pass.

