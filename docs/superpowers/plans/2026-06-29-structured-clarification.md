# Structured Clarification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 ReAct 旅行 Agent 增加结构化澄清：信息不足时后端发出 `clarify` SSE，前端展示问题和选项，用户下一轮用同一 `thread_id` 继续。

**Architecture:** 不照搬 Hermes 的阻塞等待；采用短连接协议：Agent 调用澄清工具写入 `clarification_request`，`sse_events` 检测后发 `clarify` 并结束本轮。前端把 `clarify` 渲染成 assistant 气泡和选项按钮，点击选项复用现有 `send()`。

**Tech Stack:** FastAPI · LangGraph `create_agent` · LangChain tools · SSE · pytest · Vue 3 `<script setup>` · Pinia · TypeScript · Element Plus · bun build。

## Global Constraints

- 中文优先：面向用户的澄清问题、按钮和文档用中文。
- 简洁优先：只实现缺口澄清，不实现阻塞等待、超时、独立 `/clarify/respond` API。
- 精准修改：只触及澄清协议、Agent 工具、SSE 桥接和聊天 UI。
- TDD：后端行为先写 pytest 失败用例；前端至少先用类型/构建暴露契约缺口，再实现。
- 安全：SSE 错误仍脱敏，不向前端暴露堆栈或密钥。

---

## File Structure

- `backend/app/core/constants.py`：新增 `EVENT_CLARIFY` 常量。
- `backend/app/agent/state.py`：新增 `clarification_request` 状态字段。
- `backend/app/agent/tools/clarify.py`：新增 `ask_clarification` 工具，负责参数规范化并写 state。
- `backend/app/agent/tools/__init__.py`：导出澄清工具。
- `backend/app/agent/build.py`：注册澄清工具。
- `backend/app/agent/prompt.py`：要求缺关键条件时调用澄清工具。
- `backend/app/graph/stream.py`：检测澄清 state，发 `clarify` 后结束本轮。
- `backend/tests/test_chat_stream.py`：新增 SSE 澄清行为测试。
- `backend/tests/agent/test_tools.py`：新增澄清工具参数规范化测试。
- `frontend/src/types/index.ts`：新增 `ClarifyPayload` 和 `clarify` 事件名。
- `frontend/src/stores/trip.ts`：让 `Message` 支持 `clarify` 数据和 store action。
- `frontend/src/composables/useSSE.ts`：处理 `clarify` 事件。
- `frontend/src/components/MessageList.vue`：显示澄清选项并抛出选择事件。
- `frontend/src/components/ChatPanel.vue`：把澄清选项选择转发给 `send()`。
- `plan/20260629_structured_clarification/README.md`：记录本次改动。

## Task 1: Backend Clarification Contract

**Files:**
- Modify: `backend/app/core/constants.py`
- Modify: `backend/app/agent/state.py`
- Create: `backend/app/agent/tools/clarify.py`
- Modify: `backend/app/agent/tools/__init__.py`
- Modify: `backend/app/agent/build.py`
- Modify: `backend/app/agent/prompt.py`
- Test: `backend/tests/agent/test_tools.py`
- Test: `backend/tests/test_chat_stream.py`

**Interfaces:**
- Produces: `ask_clarification(field: str, question: str, options: list[str] | None, tool_call_id: str) -> Command`
- Produces state: `clarification_request = {"field": str, "question": str, "options": list[str]}`
- Produces SSE event: `clarify` with same payload.

- [ ] **Step 1: Write failing tool tests**

Add tests to `backend/tests/agent/test_tools.py`:

```python
async def test_ask_clarification_writes_structured_request():
    cmd = await tools.ask_clarification.ainvoke({
        "field": "city",
        "question": "你想去哪个城市？",
        "options": ["成都", "重庆", "顺德", "其他"],
        "tool_call_id": "clarify-1",
    })

    request = cmd.update["clarification_request"]
    assert request == {
        "field": "city",
        "question": "你想去哪个城市？",
        "options": ["成都", "重庆", "顺德", "其他"],
    }
    assert cmd.update["messages"][0].tool_call_id == "clarify-1"


async def test_ask_clarification_trims_options_to_four_and_drops_blank_values():
    cmd = await tools.ask_clarification.ainvoke({
        "field": "days",
        "question": "你打算玩几天？",
        "options": [" 2 天 ", "", "3 天", "4 天", "5 天"],
        "tool_call_id": "clarify-2",
    })

    assert cmd.update["clarification_request"] == {
        "field": "days",
        "question": "你打算玩几天？",
        "options": ["2 天", "3 天", "4 天", "5 天"],
    }
```

- [ ] **Step 2: Run tool tests to verify RED**

Run: `cd backend && uv run pytest tests/agent/test_tools.py -q`

Expected: FAIL because `tools.ask_clarification` does not exist.

- [ ] **Step 3: Write failing SSE test**

Add fake graph and test to `backend/tests/test_chat_stream.py`:

```python
class _FakeGraphWithClarification:
    def __init__(self):
        self._state_calls = 0

    async def aget_state(self, _config):
        self._state_calls += 1
        if self._state_calls == 1:
            return SimpleNamespace(values={})
        return SimpleNamespace(values={
            "messages": [],
            "clarification_request": {
                "field": "city",
                "question": "你想去哪个城市？",
                "options": ["成都", "重庆"],
            },
            "day_plans": [],
            "budget_check": {},
            "plan_version": 0,
            "changed_days": [],
        })

    async def astream_events(self, _stream_input, *, config, version):
        yield {"event": "on_tool_start", "name": "ask_clarification", "data": {"input": {}}}
        yield {"event": "on_tool_end", "name": "ask_clarification", "data": {"input": {}}}


async def test_sse_events_emits_clarify_and_stops_without_final(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.sqlite"))
    await store.setup()
    session = await store.create_session()

    async def _is_disconnected():
        return False

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(graph=_FakeGraphWithClarification(), session_store=store)),
        is_disconnected=_is_disconnected,
    )

    events = [event async for event in sse_events("帮我做旅行攻略", session["thread_id"], request)]

    assert "clarify" in [event["event"] for event in events]
    assert "final" not in [event["event"] for event in events]
    clarify = next(event for event in events if event["event"] == "clarify")
    assert json.loads(clarify["data"]) == {
        "field": "city",
        "question": "你想去哪个城市？",
        "options": ["成都", "重庆"],
    }
    messages = await store.list_ui_messages(session["thread_id"])
    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "帮我做旅行攻略"),
        ("assistant", "你想去哪个城市？"),
    ]
```

- [ ] **Step 4: Run SSE test to verify RED**

Run: `cd backend && uv run pytest tests/test_chat_stream.py::test_sse_events_emits_clarify_and_stops_without_final -q`

Expected: FAIL because `clarify` event is not emitted.

- [ ] **Step 5: Implement backend contract**

Implementation requirements:
- Add `EVENT_CLARIFY = "clarify"` to constants.
- Add `clarification_request: dict` to `TripState`.
- Create `backend/app/agent/tools/clarify.py` with Chinese docstring and `@tool async def ask_clarification(...)`.
- Normalize `field` and `question` with `.strip()`.
- Normalize options: only non-empty strings, trim whitespace, max 4.
- Return `Command(update={"clarification_request": request, "messages": [ToolMessage(...)]})`.
- Export and register `ask_clarification`.
- Update prompt: when missing city/days/date/budget or other key condition, call `ask_clarification`; ask one key question at a time; put choices in `options`.

- [ ] **Step 6: Implement SSE clarify branch**

In `sse_events`, after graph streaming and before final assembly:
- read `values.get("clarification_request")`;
- if dict with `question`, mark running tool steps done;
- persist user message;
- persist assistant message as question with tool steps;
- yield `EVENT_CLARIFY`;
- update title if needed;
- return without `EVENT_FINAL`.

- [ ] **Step 7: Run backend tests**

Run:

```bash
cd backend
uv run pytest tests/agent/test_tools.py tests/test_chat_stream.py tests/agent/test_build_agent.py -q
```

Expected: PASS.

## Task 2: Frontend Clarification UI

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/stores/trip.ts`
- Modify: `frontend/src/composables/useSSE.ts`
- Modify: `frontend/src/components/MessageList.vue`
- Modify: `frontend/src/components/ChatPanel.vue`

**Interfaces:**
- Consumes SSE payload: `ClarifyPayload { field: string; question: string; options: string[] }`
- Produces store action: `addClarifyMessage(payload: ClarifyPayload): void`
- Produces UI event: `MessageList` emits `clarify-answer` with answer string.

- [ ] **Step 1: Add frontend type contract first**

Modify `frontend/src/types/index.ts`:

```ts
export interface ClarifyPayload { field: string; question: string; options: string[] }
```

Add `'clarify'` to `EventName`.

- [ ] **Step 2: Run build to expose missing handling**

Run: `cd frontend && bun run build`

Expected: It may still pass because switch exhaustiveness is not enforced; treat this as the type-contract checkpoint before UI implementation.

- [ ] **Step 3: Implement store data shape**

Modify `Message` in `frontend/src/stores/trip.ts`:

```ts
clarify?: ClarifyPayload
```

Import `ClarifyPayload`. Add:

```ts
const addClarifyMessage = (payload: ClarifyPayload) => {
  activeConversation.value?.messages.push({
    role: 'assistant',
    content: payload.question,
    kind: 'text',
    clarify: payload,
  })
}
```

Return `addClarifyMessage`.

- [ ] **Step 4: Implement SSE handler**

In `frontend/src/composables/useSSE.ts`:
- import `ClarifyPayload`;
- add `case 'clarify': tripStore.addClarifyMessage(data as ClarifyPayload); tripStore.touchActive(); loading.value = false; break`.

- [ ] **Step 5: Implement MessageList option UI**

In `MessageList.vue`:
- add `const emit = defineEmits<{ (e: 'clarify-answer', answer: string): void }>()`;
- under markdown content, render `msg.clarify?.options` as Element Plus small buttons;
- on click emit option text.

- [ ] **Step 6: Wire ChatPanel**

In `ChatPanel.vue`:
- change `<MessageList ... />` to listen for `@clarify-answer="send"`.

- [ ] **Step 7: Run frontend build**

Run: `cd frontend && bun run build`

Expected: PASS.

## Task 3: Record and Full Verification

**Files:**
- Create: `plan/20260629_structured_clarification/README.md`

**Interfaces:**
- Produces project-required change record with task goal, file list, details, test results, decisions.

- [ ] **Step 1: Create change record**

Create `plan/20260629_structured_clarification/README.md` with:
- 任务目标
- 改动文件清单
- 改动详情
- 测试结果
- 相关讨论

- [ ] **Step 2: Run full focused verification**

Run:

```bash
cd backend
uv run pytest -q
```

Run:

```bash
cd frontend
bun run build
```

Expected: both PASS.

- [ ] **Step 3: Inspect diff**

Run: `git diff --stat` and `git diff --check`.

Expected: no whitespace errors; diff only touches planned files.

