# 聊天交错渲染 + 澄清浮层面板 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把对话消息改造为按到达顺序交错的「文本/工具」片段（codex 风格），中间推理淡色可折叠、最终回复黑色常展开；澄清改为输入框上方浮层面板含选项+自定义填写；segments 贯穿实时流、SQLite 历史、graph 重建三条路径，保证实时与历史完全一致。

**Architecture:** 用统一的 `Segment` 数据结构（`text` 段 / `tool` 段交错有序列表）取代「`content: string` + `tool_steps: []`」。后端三处产出 segments：`stream.py` 流式按到达顺序攒、`session_store` 持久化新增 `segments` 列、`message_history` graph 重建产出 segments。前端 store 持有 `Message.segments`，`MessageList` 顺序渲染并在渲染期判定 reasoning/answer。澄清新增 `pendingClarify` 状态驱动 `ClarifyPanel` 浮层。

**Tech Stack:** 后端 Python 3.12 / FastAPI / aiosqlite / pytest（asyncio_mode=auto）；前端 Vue 3 `<script setup lang="ts">` / Pinia / Element Plus / vue-tsc。

## Global Constraints

- 后端用 `uv run pytest -q` 跑测试，对 LLM/高德打桩，不依赖真实 Key/网络。
- 前端用 `bun run build`（= `vue-tsc -b && vite build`）作为契约校验，须全绿。
- agent tool 写回 state 用 `Command(update={...})` 带 `ToolMessage`；本计划不新增 tool。
- SSE `error` 事件须脱敏，不含 Key/堆栈。
- 完成后须在 `plan/YYYYMMDD_<任务简述>/README.md` 写改动记录（见 Task 11）。
- 提交信息行尾加：`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。

## 数据契约（贯穿全计划，前后端必须一致）

**后端 segment dict（Python）：**
```python
# text 段
{"kind": "text", "text": "<文本>"}
# tool 段（历史一律 done，实时流过程中可为 running）
{"kind": "tool", "tool": "<工具名>", "label": "<中文文案>", "status": "done"}
```

**前端 Segment（TS）：**
```ts
export type Segment =
  | { kind: 'text'; text: string }
  | { kind: 'tool'; tool: string; label: string; status: 'running' | 'done' }
```

**reasoning / answer 不存储**：渲染期判定——segments 中**最后一个** `kind==='text'` 段为
`answer`（黑色常展开），其余 text 段为 `reasoning`（淡色、可折叠）。

**list_ui_messages 返回 dict**（向后兼容，新增 `segments`）：
```python
{"role": str, "content": str, "kind": str, "tool_steps": list[dict], "segments": list[dict]}
```
assistant 消息前端只读 `segments`；user/error 消息读 `content`。

---

### Task 1: 后端 segments 构建纯函数（message_history.py）

把 ReAct 一轮内的 AIMessage 序列按出现顺序转成交错的 segments。纯函数、无副作用、单独测。

**Files:**
- Modify: `backend/app/services/message_history.py`
- Test: `backend/tests/test_session_aggregate.py`

**Interfaces:**
- Produces:
  - `build_segments(messages: list) -> list[dict]` —— 输入 LangGraph 消息列表（一轮或多轮），
    输出交错 segments。规则：遇 `HumanMessage`（非 summarization）开启新一轮但**不**产出 user 段
    （user 段由调用方单独处理）；`AIMessage` 先把非空文本块 push 为 text 段，再把其 `tool_calls`
    依次 push 为 tool 段（`status="done"`，label 用 `build_tool_label`）；`ToolMessage`/`SystemMessage` 跳过。
  - `segments_for_assistant(messages: list) -> list[dict]` —— 仅返回**最后一个用户回合**之后的
    assistant segments（供 graph 重建单轮场景）。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_session_aggregate.py` 末尾追加：

```python
from app.services.message_history import build_segments


def test_build_segments_interleaves_text_and_tools():
    messages = [
        AIMessage(content="我先查一下天气。", tool_calls=[
            {"name": "get_weather", "args": {"city": "成都"}, "id": "c0"},
        ]),
        ToolMessage(content="晴", tool_call_id="c0"),
        AIMessage(content="天气不错，再看看景点。", tool_calls=[
            {"name": "search_attractions", "args": {"city": "成都"}, "id": "c1"},
        ]),
        ToolMessage(content="武侯祠等", tool_call_id="c1"),
        AIMessage(content="这是你的成都行程。"),
    ]

    segments = build_segments(messages)

    assert segments == [
        {"kind": "text", "text": "我先查一下天气。"},
        {"kind": "tool", "tool": "get_weather", "label": "查询成都天气", "status": "done"},
        {"kind": "text", "text": "天气不错，再看看景点。"},
        {"kind": "tool", "tool": "search_attractions", "label": "搜索成都景点", "status": "done"},
        {"kind": "text", "text": "这是你的成都行程。"},
    ]


def test_build_segments_skips_empty_text_and_tool_messages():
    messages = [
        SystemMessage(content="你是助手"),
        AIMessage(content="", tool_calls=[{"name": "get_weather", "args": {}, "id": "c0"}]),
        ToolMessage(content="晴", tool_call_id="c0"),
        AIMessage(content="好了。"),
    ]

    segments = build_segments(messages)

    assert segments == [
        {"kind": "tool", "tool": "get_weather", "label": "查询天气", "status": "done"},
        {"kind": "text", "text": "好了。"},
    ]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/test_session_aggregate.py::test_build_segments_interleaves_text_and_tools -v`
Expected: FAIL —— `ImportError: cannot import name 'build_segments'`

- [ ] **Step 3: 实现 build_segments**

在 `backend/app/services/message_history.py` 的 `tool_steps` 函数后追加：

```python
def _tool_segments(message) -> list[dict]:
    """把一个 AIMessage 的 tool_calls 转成 tool 段（历史一律 done）。"""
    return [
        {
            "kind": "tool",
            "tool": tc["name"],
            "label": build_tool_label(tc.get("name"), tc.get("args") or {}),
            "status": "done",
        }
        for tc in (getattr(message, "tool_calls", None) or [])
    ]


def build_segments(messages) -> list[dict]:
    """把一轮内的 AIMessage 序列按出现顺序转成交错的 text/tool 段。

    意图：让历史回放与实时流呈现同一形态——文本与工具按时间顺序交错，
    而非「正文一坨 + 工具一坨」。ToolMessage/SystemMessage 跳过；空文本块不产出 text 段。
    """
    segments: list[dict] = []
    for message in messages:
        if isinstance(message, (ToolMessage, SystemMessage)):
            continue
        if isinstance(message, HumanMessage):
            if is_summarization_message(message):
                continue
            continue  # user 段由调用方处理，这里只攒 assistant 内容
        if isinstance(message, AIMessage):
            text = extract_content(message)
            if text:
                segments.append({"kind": "text", "text": text})
            segments.extend(_tool_segments(message))
    return segments


def segments_for_assistant(messages) -> list[dict]:
    """仅返回最后一个用户回合之后的 assistant segments。"""
    last_human = -1
    for idx, message in enumerate(messages):
        if isinstance(message, HumanMessage) and not is_summarization_message(message):
            last_human = idx
    return build_segments(messages[last_human + 1:])
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/test_session_aggregate.py -k build_segments -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/message_history.py backend/tests/test_session_aggregate.py
git commit -m "feat(history): 新增 build_segments 交错文本与工具段

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: session_store 持久化 segments 列 + 读写 + 旧数据降级

给 `session_messages` 表加 `segments` 列（幂等迁移），`append_ui_message` 写入、`list_ui_messages`
优先读 segments、旧行降级合成。

**Files:**
- Modify: `backend/app/services/session_store.py`
- Test: `backend/tests/test_sessions.py`

**Interfaces:**
- Consumes: `build_tool_label`（已存在，降级时不需要，旧行已存 label）。
- Produces:
  - `append_ui_message(thread_id, role, content, *, kind="text", tool_steps=None, segments=None)` ——
    新增 `segments` 关键字参数，json 序列化写入新列。
  - `list_ui_messages(thread_id) -> list[dict]` —— 每条带 `segments` 键；旧行（segments 列为 `[]`）
    降级：tool_steps 各转 `{"kind":"tool",...,"status":"done"}` 在前，content 非空则追加
    `{"kind":"text","text":content}` 在后。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_sessions.py` 末尾追加（若文件无 `import pytest`/`SessionStore` 则一并加）：

```python
import pytest
from app.services.session_store import SessionStore


@pytest.mark.anyio
async def test_append_and_list_segments_roundtrip(tmp_path):
    store = SessionStore(str(tmp_path / "s.sqlite"))
    await store.setup()
    session = await store.create_session()
    segments = [
        {"kind": "text", "text": "先查天气"},
        {"kind": "tool", "tool": "get_weather", "label": "查询成都天气", "status": "done"},
        {"kind": "text", "text": "成都行程如下"},
    ]
    await store.append_ui_message(
        session["thread_id"], "assistant", "先查天气成都行程如下",
        tool_steps=[{"tool": "get_weather", "label": "查询成都天气", "status": "done"}],
        segments=segments,
    )

    messages = await store.list_ui_messages(session["thread_id"])

    assert messages[0]["segments"] == segments


@pytest.mark.anyio
async def test_list_segments_degrades_legacy_rows(tmp_path):
    """旧行无 segments：tool_steps 转 tool 段在前，content 转 text 段在后。"""
    store = SessionStore(str(tmp_path / "s.sqlite"))
    await store.setup()
    session = await store.create_session()
    # 不传 segments，模拟旧数据写入路径
    await store.append_ui_message(
        session["thread_id"], "assistant", "这是答案",
        tool_steps=[{"tool": "get_weather", "label": "查询天气", "status": "done"}],
    )

    messages = await store.list_ui_messages(session["thread_id"])

    assert messages[0]["segments"] == [
        {"kind": "tool", "tool": "get_weather", "label": "查询天气", "status": "done"},
        {"kind": "text", "text": "这是答案"},
    ]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/test_sessions.py::test_append_and_list_segments_roundtrip -v`
Expected: FAIL —— `TypeError: append_ui_message() got an unexpected keyword argument 'segments'`

- [ ] **Step 3: 实现表迁移与读写**

在 `backend/app/services/session_store.py` 的 `setup()` 内、`CREATE INDEX` 之后、`await db.commit()` 之前插入幂等迁移：

```python
            # 幂等迁移：旧库 session_messages 无 segments 列时补列（SQLite 支持 ADD COLUMN）
            cursor = await db.execute("PRAGMA table_info(session_messages)")
            cols = [row[1] for row in await cursor.fetchall()]
            if "segments" not in cols:
                await db.execute(
                    "ALTER TABLE session_messages ADD COLUMN segments TEXT NOT NULL DEFAULT '[]'"
                )
```

并在新建表的 `CREATE TABLE session_messages` 里加 `segments` 列（新库直接带列）：

```python
                CREATE TABLE IF NOT EXISTS session_messages (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  thread_id TEXT NOT NULL,
                  role TEXT NOT NULL,
                  content TEXT NOT NULL,
                  kind TEXT NOT NULL DEFAULT 'text',
                  tool_steps TEXT NOT NULL DEFAULT '[]',
                  segments TEXT NOT NULL DEFAULT '[]',
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(thread_id) REFERENCES session_meta(thread_id)
                )
```

把 `append_ui_message` 改为：

```python
    async def append_ui_message(
        self,
        thread_id: str,
        role: str,
        content: str,
        *,
        kind: str = "text",
        tool_steps: list[dict] | None = None,
        segments: list[dict] | None = None,
    ) -> None:
        now = _now_iso()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO session_messages
                  (thread_id, role, content, kind, tool_steps, segments, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thread_id,
                    role,
                    content,
                    kind,
                    json.dumps(tool_steps or [], ensure_ascii=False),
                    json.dumps(segments or [], ensure_ascii=False),
                    now,
                ),
            )
            await db.commit()
```

把 `list_ui_messages` 的 SELECT 与组装改为：

```python
            rows = await db.execute_fetchall(
                """
                SELECT role, content, kind, tool_steps, segments
                FROM session_messages
                WHERE thread_id = ?
                ORDER BY id ASC
                """,
                (thread_id,),
            )
        messages = []
        for row in rows:
            try:
                tool_steps = json.loads(row["tool_steps"] or "[]")
            except json.JSONDecodeError:
                tool_steps = []
            try:
                segments = json.loads(row["segments"] or "[]")
            except json.JSONDecodeError:
                segments = []
            if not segments:
                # 旧数据降级：工具段在前（done），正文段在后
                segments = [
                    {"kind": "tool", "tool": s.get("tool"), "label": s.get("label"), "status": "done"}
                    for s in tool_steps
                ]
                if row["content"]:
                    segments.append({"kind": "text", "text": row["content"]})
            messages.append({
                "role": row["role"],
                "content": row["content"],
                "kind": row["kind"],
                "tool_steps": tool_steps,
                "segments": segments,
            })
        return messages
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/test_sessions.py -k segments -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/session_store.py backend/tests/test_sessions.py
git commit -m "feat(store): session_messages 持久化 segments 列并降级旧数据

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: stream.py 流式按到达顺序攒 segments 并落库

把 `sse_events` 内现有的 `answer_parts`/`tool_steps` 收集逻辑改造为按到达顺序维护 `segments`，
结束时 `append_ui_message(..., segments=segments)`。澄清分支、笔记来源追加同步走 segments。

**Files:**
- Modify: `backend/app/graph/stream.py`
- Test: `backend/tests/test_chat_stream.py`

**Interfaces:**
- Consumes: `build_tool_label`、`render_xhs_sources`（已存在）；`append_ui_message(..., segments=...)`（Task 2）。
- Produces: 落库 assistant 消息的 `segments` 与实时流到达顺序一致。

注意：现有测试 `test_sse_events_persists_ui_history_matching_realtime_stream` 等断言 `list_ui_messages`
返回 dict **不含** segments 键。Task 2 已让其恒含 `segments`，故这些旧断言需更新为带 segments。

- [ ] **Step 1: 改写失败测试**

把 `backend/tests/test_chat_stream.py` 中 `test_sse_events_persists_ui_history_matching_realtime_stream`
的 `assert messages == [...]` 块替换为（其余不变）：

```python
    assert messages == [
        {"role": "user", "content": "帮我做顺德旅行攻略", "kind": "text",
         "tool_steps": [], "segments": [{"kind": "text", "text": "帮我做顺德旅行攻略"}]},
        {
            "role": "assistant",
            "content": token_text,
            "kind": "text",
            "tool_steps": [
                {"tool": "research_xhs_travel_guide", "label": "研究顺德1天美食小红书攻略", "status": "done"},
            ],
            "segments": [
                {"kind": "tool", "tool": "research_xhs_travel_guide",
                 "label": "研究顺德1天美食小红书攻略", "status": "done"},
                {"kind": "text", "text": token_text},
            ],
        },
    ]
```

> 说明：`_FakeGraphWithSources` 先发 tool_start/tool_end，再发一段文本 token，最后追加笔记来源 md
> 到该文本段。故 assistant segments 为「tool 段 + 单个 text 段（正文+笔记来源）」。

并在该文件末尾追加一条**交错顺序**新测试：

```python
class _FakeGraphInterleaved:
    def __init__(self):
        self._state_calls = 0

    async def aget_state(self, _config):
        self._state_calls += 1
        if self._state_calls == 1:
            return SimpleNamespace(values={"xhs_sources": []})
        return SimpleNamespace(values={
            "messages": [AIMessage(content="成都行程如下。")],
            "xhs_sources": [],
            "day_plans": [], "budget_check": {}, "plan_version": 0, "changed_days": [],
        })

    async def astream_events(self, _stream_input, *, config, version):
        yield {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="我先查天气。")}}
        yield {"event": "on_tool_start", "name": "get_weather", "data": {"input": {"city": "成都"}}}
        yield {"event": "on_tool_end", "name": "get_weather", "data": {"input": {"city": "成都"}}}
        yield {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="成都行程如下。")}}


@pytest.mark.anyio
async def test_sse_events_persists_interleaved_segments(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.sqlite"))
    await store.setup()
    session = await store.create_session()

    async def _is_disconnected():
        return False

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(graph=_FakeGraphInterleaved(), session_store=store)),
        is_disconnected=_is_disconnected,
    )

    [event async for event in sse_events("成都三天", session["thread_id"], request)]
    messages = await store.list_ui_messages(session["thread_id"])

    assistant = messages[1]
    assert assistant["segments"] == [
        {"kind": "text", "text": "我先查天气。"},
        {"kind": "tool", "tool": "get_weather", "label": "查询成都天气", "status": "done"},
        {"kind": "text", "text": "成都行程如下。"},
    ]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/test_chat_stream.py::test_sse_events_persists_interleaved_segments -v`
Expected: FAIL —— assistant segments 不含交错结构（落库未攒 segments）。

- [ ] **Step 3: 改写 stream.py 攒 segments**

在 `sse_events` 中，`tool_steps: list[dict] = []` 之后新增片段累积器与辅助：

```python
        segments: list[dict] = []

        def _push_token_segment(text: str) -> None:
            """token 到达：末尾是 text 段则追加，否则新开一段（工具天然分界）。"""
            if segments and segments[-1]["kind"] == "text":
                segments[-1]["text"] += text
            else:
                segments.append({"kind": "text", "text": text})
```

在 `on_chat_model_stream` 分支里，`yield _sse(EVENT_TOKEN, ...)` 之前加 `_push_token_segment(text)`：

```python
            if kind == "on_chat_model_stream":
                chunk = ev["data"]["chunk"]
                text = _as_text(chunk.content)
                if text:
                    answer_parts.append(text)
                    _push_token_segment(text)
                    yield _sse(EVENT_TOKEN, {"text": text})
```

在 `on_tool_start` 分支里，append tool_steps 之后、yield 之前，追加 tool 段：

```python
            elif kind == "on_tool_start":
                label = build_tool_label(name, _tool_input(ev))
                for step in tool_steps:
                    if step["status"] == "running":
                        step["status"] = "done"
                for seg in segments:
                    if seg["kind"] == "tool" and seg["status"] == "running":
                        seg["status"] = "done"
                tool_steps.append({"tool": name, "label": label, "status": "running"})
                segments.append({"kind": "tool", "tool": name, "label": label, "status": "running"})
                yield _sse(EVENT_TOOL_CALL, {"tool": name, "label": label})
```

在 `on_tool_end` 分支里，把对应 tool 段标记 done（紧跟现有 tool_steps 收尾逻辑后）：

```python
            elif kind == "on_tool_end":
                label = build_tool_label(name, _tool_input(ev))
                for step in reversed(tool_steps):
                    if step["tool"] == name and step["status"] == "running":
                        step["status"] = "done"
                        label = step["label"]
                        break
                for seg in reversed(segments):
                    if seg["kind"] == "tool" and seg["tool"] == name and seg["status"] == "running":
                        seg["status"] = "done"
                        break
                if name == "ask_clarification":
                    asked_clarification = True
                yield _sse(EVENT_TOOL_RESULT, {"tool": name, "label": label})
```

在流循环结束后，收尾 running tool 段（与 tool_steps 收尾并列处理）。找到 `for step in tool_steps: if step["status"] == "running": step["status"] = "done"`（最终分支那处，约第 172 行）后，紧接着加：

```python
        for seg in segments:
            if seg["kind"] == "tool" and seg["status"] == "running":
                seg["status"] = "done"
```

笔记来源：现有 `if answer and len(xhs_sources) > prior_source_count:` 块里，把 `sources_md`
追加到 segments 的最后一个 text 段（无则新开）。在 `answer = answer + sources_md` 之后加：

```python
                _push_token_segment(sources_md)
```

落库：把最终分支的 `append_ui_message(thread_id, "assistant", ui_answer, tool_steps=tool_steps)`
改为带 segments：

```python
        if ui_answer or tool_steps:
            await session_store.append_ui_message(
                thread_id,
                "assistant",
                ui_answer,
                tool_steps=tool_steps,
                segments=segments,
            )
```

澄清分支：在 `yield _sse(EVENT_CLARIFY, payload)` 之前的 `append_ui_message(thread_id, "assistant", payload["question"], tool_steps=tool_steps)` 改为带 segments（澄清问题作为单个 text 段 + 已有工具段）：

```python
            clarify_segments = list(segments)
            clarify_segments.append({"kind": "text", "text": payload["question"]})
            await session_store.append_ui_message(
                thread_id,
                "assistant",
                payload["question"],
                tool_steps=tool_steps,
                segments=clarify_segments,
            )
```

> 注：user 消息落库 `append_ui_message(thread_id, "user", message)` 不传 segments，Task 2 的降级逻辑
> 会自动把 content 合成单个 text 段，故 user 段断言为 `[{"kind":"text","text":message}]`。

- [ ] **Step 4: 运行全量流式测试**

Run: `cd backend && uv run pytest tests/test_chat_stream.py -v`
Expected: PASS（含新测试与更新后的旧测试）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/stream.py backend/tests/test_chat_stream.py
git commit -m "feat(stream): 流式按到达顺序攒 segments 并落库

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: sessions.py 快照走 segments（graph 重建 + 笔记来源追加）

`_snapshot` 经 `list_ui_messages`（已带 segments）或 graph 重建产出 segments；笔记来源 md 追加到
最后一个 text 段而非 content 尾。

**Files:**
- Modify: `backend/app/services/message_history.py`（`messages_with_xhs_sources`、`reconstruct_messages_from_history`）
- Modify: `backend/app/api/sessions.py`
- Test: `backend/tests/test_session_aggregate.py`

**Interfaces:**
- Consumes: `build_segments` / `segments_for_assistant`（Task 1）。
- Produces:
  - `reconstruct_messages_from_history(history_values) -> list[dict]` —— 每条 assistant dict 带 `segments`。
  - `messages_with_xhs_sources(messages, sources) -> list[dict]` —— 把来源 md 追加到最近 assistant
    的最后一个 text 段（无 text 段则新开），并保持 `content` 同步以兼容纯文本检索。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_session_aggregate.py` 追加：

```python
def test_messages_with_xhs_sources_appends_to_last_text_segment():
    sources_md_marker = "## 笔记来源"
    messages = [
        {
            "role": "assistant",
            "content": "这是顺德攻略。",
            "kind": "text",
            "tool_steps": [],
            "segments": [{"kind": "text", "text": "这是顺德攻略。"}],
        },
    ]
    sources = [{"title": "顺德一日游", "url": "https://www.xiaohongshu.com/explore/note-1"}]

    result = _messages_with_xhs_sources(messages, sources)

    last_text = [s for s in result[0]["segments"] if s["kind"] == "text"][-1]
    assert sources_md_marker in last_text["text"]
    assert "note-1" in last_text["text"]
    assert sources_md_marker in result[0]["content"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/test_session_aggregate.py::test_messages_with_xhs_sources_appends_to_last_text_segment -v`
Expected: FAIL —— segments 未被追加来源。

- [ ] **Step 3: 实现 segments 感知的来源追加与重建**

把 `message_history.py` 的 `messages_with_xhs_sources` 改为：

```python
def messages_with_xhs_sources(messages: list[dict], sources: list[dict]) -> list[dict]:
    """把渲染好的小红书来源链接追加到最近 assistant 消息（content 与 segments 同步）。"""
    sources_md = render_xhs_sources(sources)
    if not sources_md:
        return messages
    result = [dict(message) for message in messages]
    for message in reversed(result):
        if message.get("role") != "assistant":
            continue
        content = message.get("content") or ""
        if "## 笔记来源" in content:
            break
        message["content"] = f"{content}{sources_md}" if content else sources_md.lstrip()
        segments = [dict(s) for s in (message.get("segments") or [])]
        text_segs = [s for s in segments if s.get("kind") == "text"]
        if text_segs:
            text_segs[-1]["text"] = f"{text_segs[-1]['text']}{sources_md}"
        else:
            segments.append({"kind": "text", "text": sources_md.lstrip()})
        message["segments"] = segments
        break
    return result
```

把 `reconstruct_messages_from_history` 的返回 assistant dict 改为带 segments：在该函数末尾
`result.append({...})` 处，给 assistant dict 加 `segments`（用 `build_segments` 重建最新一轮）：

```python
    result = user_messages[:1]
    if assistant_content or assistant_tools:
        rebuilt = segments_for_assistant((history_values[0] or {}).get("messages", []) or [])
        if not rebuilt:
            rebuilt = [{"kind": "tool", **{k: v for k, v in s.items() if k != "status"}, "status": "done"}
                       for s in assistant_tools]
            if assistant_content:
                rebuilt.append({"kind": "text", "text": assistant_content})
        result.append({
            "role": "assistant",
            "content": assistant_content,
            "kind": "text",
            "tool_steps": assistant_tools,
            "segments": rebuilt,
        })
    return result
```

并在 `message_history.py` 顶部确保 `from app.services.tool_labels import build_tool_label` 已存在
（已存在），新增导入 `segments_for_assistant` 无需——同模块内函数。

`aggregate_messages` 给每条 assistant 也补 `segments` 键（供 `list_ui_messages` 之外的 graph-only 路径）：
在 `aggregate_messages` 内 `current_ai` 初始化处加 `"segments": build_segments([message])`，
并在合并分支 `current_ai["tool_steps"].extend(...)` 同处 `current_ai["segments"].extend(build_segments([message]))`。
替换原 `current_ai` 构造块为：

```python
            if current_ai is None:
                current_ai = {
                    "role": "assistant",
                    "content": content,
                    "kind": "text",
                    "tool_steps": tool_steps(message),
                    "segments": build_segments([message]),
                }
                result.append(current_ai)
            else:
                current_ai["tool_steps"].extend(tool_steps(message))
                current_ai["segments"].extend(build_segments([message]))
                if content:
                    current_ai["content"] = (
                        f"{current_ai['content']}{content}" if current_ai["content"] else content
                    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/test_session_aggregate.py -v`
Expected: PASS（含原有聚合测试 + 新增 segments 测试）

> 若原有 `test_messages_with_xhs_sources_*` 断言 `tool_steps` 不变仍成立（未触碰）；
> 若因 dict 拷贝顺序报错，调整断言读 `result[1]["segments"]`。

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/message_history.py backend/app/api/sessions.py backend/tests/test_session_aggregate.py
git commit -m "feat(sessions): 快照走 segments，笔记来源追加到末尾文本段

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: 前端类型与 store segments 结构 + pendingClarify

定义 `Segment` 类型，`Message.segments` 取代 `content+toolSteps`，改造 token/tool 写入函数，
新增 `pendingClarify` 状态。

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/stores/trip.ts`

**Interfaces:**
- Produces（store actions，供 Task 6/7 消费）：
  - `appendToken(text: string): void`
  - `startToolCall(tool: string, label: string): void`
  - `endToolCall(tool: string): void`
  - `pendingClarify: Ref<ClarifyPayload | null>`、`setPendingClarify(p: ClarifyPayload | null): void`
  - `Message.segments: Segment[]`

- [ ] **Step 1: 加类型**

在 `frontend/src/types/index.ts` 顶部（`ClarifyPayload` 附近）新增：

```ts
export type Segment =
  | { kind: 'text'; text: string }
  | { kind: 'tool'; tool: string; label: string; status: 'running' | 'done' }
```

把 `SessionSnapshot.messages` 元素结构改为带 segments：

```ts
  messages: Array<{
    role: 'user' | 'assistant'
    content: string
    kind?: 'text' | 'error'
    tool_steps?: Array<{ tool: string; label: string; status: 'done' }>
    segments?: Segment[]
  }>
```

- [ ] **Step 2: 改 store —— Message 结构与 actions**

在 `frontend/src/stores/trip.ts`，把 `Message` 接口改为：

```ts
import type { DayPlan, Budget, TripItem, SessionSnapshot, ClarifyPayload, Segment } from '../types'

export interface Message {
  role: 'user' | 'assistant'
  content: string            // user/error 用；assistant 渲染走 segments
  kind?: 'text' | 'error'
  segments?: Segment[]
  clarify?: ClarifyPayload
}
```

> 删除原 `ToolStep` 接口与 `Message.toolSteps` 字段（被 Segment 取代）。若 `ToolStep` 被其它文件
> 引用，Task 7 会一并清理；此处先改 store。

新增 `pendingClarify` 状态（在 `toolSteps` ref 附近，可删除原 `toolSteps` ref）：

```ts
  const pendingClarify = ref<ClarifyPayload | null>(null)
  const setPendingClarify = (p: ClarifyPayload | null) => { pendingClarify.value = p }
```

`clearProgress` 改为同时清 pendingClarify：

```ts
  const clearProgress = () => {
    agentProgress.value = {}
    nodeLabels.value = {}
    pendingClarify.value = null
  }
```

把 `appendToLastMessage` 替换为 `appendToken`：

```ts
  const appendToken = (text: string) => {
    const msg = ensureAssistantMessage()
    if (!msg) return
    if (!msg.segments) msg.segments = []
    const last = msg.segments[msg.segments.length - 1]
    if (last && last.kind === 'text') last.text += text
    else msg.segments.push({ kind: 'text', text })
  }
```

`ensureAssistantMessage` 新建空消息改为带空 segments：

```ts
    const msg: Message = { role: 'assistant', content: '', kind: 'text', segments: [] }
```

`startToolCall` / `endToolCall` 改为操作 segments：

```ts
  const startToolCall = (tool: string, label: string) => {
    const msg = ensureAssistantMessage()
    if (!msg) return
    if (!msg.segments) msg.segments = []
    for (const s of msg.segments) if (s.kind === 'tool' && s.status === 'running') s.status = 'done'
    msg.segments.push({ kind: 'tool', tool, label, status: 'running' })
  }
  const endToolCall = (tool: string) => {
    const current = activeConversation.value
    if (!current) return
    const last = current.messages[current.messages.length - 1]
    if (last && last.role === 'assistant' && last.segments) {
      for (let i = last.segments.length - 1; i >= 0; i--) {
        const s = last.segments[i]
        if (s.kind === 'tool' && s.tool === tool && s.status === 'running') {
          s.status = 'done'
          break
        }
      }
    }
  }
```

`addClarifyMessage` 保留（仍把问题写进消息流），但同时设 pendingClarify 由 Task 6 在 useSSE 做。
把它改为写 segments 文本段：

```ts
  const addClarifyMessage = (payload: ClarifyPayload) => {
    const msg = ensureAssistantMessage()
    if (!msg) return
    if (!msg.segments) msg.segments = []
    msg.segments.push({ kind: 'text', text: payload.question })
    msg.content = payload.question
    msg.kind = 'text'
    msg.clarify = payload
  }
```

`applySnapshot` 的 messages 映射改为带 segments：

```ts
      messages: (snapshot.messages || [])
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .map((m) => ({
          role: m.role,
          content: m.content,
          kind: m.kind,
          segments: m.segments
            ? m.segments.map((s) => s.kind === 'tool' ? { ...s, status: 'done' as const } : s)
            : undefined,
        })),
```

在 store `return {...}` 里：移除 `toolSteps`、`appendToLastMessage`，加入 `appendToken`、
`pendingClarify`、`setPendingClarify`。`addMessage` 给 user/error 消息也建一个 text 段以便统一渲染：

```ts
  const addMessage = (role: 'user' | 'assistant', content: string, kind: 'text' | 'error' = 'text') => {
    activeConversation.value?.messages.push({
      role, content, kind,
      segments: [{ kind: 'text', text: content }],
    })
  }
```

- [ ] **Step 3: 类型检查（此时前端会因 MessageList 仍引用旧字段而报错，预期）**

Run: `cd frontend && bun run build`
Expected: FAIL —— `MessageList.vue`/`AgentProgress.vue` 仍引用 `toolSteps`/`appendToLastMessage`。
Task 6/7 修复后转绿。**本步仅确认 store/types 自身无语法错**（错误应只来自消费方组件）。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/types/index.ts frontend/src/stores/trip.ts
git commit -m "feat(store): Message 改为 segments 结构并加 pendingClarify

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: useSSE 走 segments + 设置 pendingClarify

事件处理改用 `appendToken`；`clarify` 事件设置 `pendingClarify`。

**Files:**
- Modify: `frontend/src/composables/useSSE.ts`

**Interfaces:**
- Consumes: `appendToken`、`setPendingClarify`、`startToolCall`、`endToolCall`（Task 5）。

- [ ] **Step 1: 改事件处理**

在 `frontend/src/composables/useSSE.ts`：
- `case 'token':` 把 `tripStore.appendToLastMessage(...)` 改为 `tripStore.appendToken((data as TokenPayload).text)`。
- `case 'clarify':` 在 `addClarifyMessage` 后加 `tripStore.setPendingClarify(data as ClarifyPayload)`：

```ts
          case 'clarify':
            tripStore.addClarifyMessage(data as ClarifyPayload)
            tripStore.setPendingClarify(data as ClarifyPayload)
            tripStore.touchActive()
            loading.value = false
            break
```

- `send` 函数开头，发送新消息时清空 pendingClarify（用户已答或开始新问）：在 `tripStore.addMessage('user', message)` 之后加 `tripStore.setPendingClarify(null)`。

- [ ] **Step 2: 类型检查（仍预期 MessageList 报错，Task 7 修）**

Run: `cd frontend && bun run build`
Expected: FAIL —— 仅 `MessageList.vue`/`AgentProgress.vue` 报错（useSSE 自身应无错）。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/composables/useSSE.ts
git commit -m "feat(sse): token 走 appendToken，clarify 设置 pendingClarify

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: MessageList 顺序渲染 segments + reasoning 折叠

按 segments 顺序渲染：tool 段为 pill，text 段按「最后一个 text=answer 黑色常展开，其余=reasoning
淡色可折叠」渲染。reasoning 段输出中（流式末段）展开，写完自动折叠。移除气泡内澄清选项。

**Files:**
- Modify: `frontend/src/components/MessageList.vue`
- Modify: `frontend/src/components/AgentProgress.vue`（退化为单 tool pill，或内联后删除引用）

**Interfaces:**
- Consumes: `Message.segments`、`tripStore.nodeLabels`/`agentProgress`（瞬态思考气泡保留）。

- [ ] **Step 1: 重写 MessageList 模板与脚本**

把 `frontend/src/components/MessageList.vue` 的 `<template>` assistant 内容区改为遍历 segments。
完整替换 `<div class="content" ...>` 内部（保留外层与 error-bubble class）：

```vue
      <div class="content" :class="{ 'error-bubble': msg.kind === 'error' }">
        <template v-for="(seg, sIdx) in displaySegments(msg)" :key="sIdx">
          <!-- 工具 pill -->
          <div v-if="seg.kind === 'tool'" class="node-pill" :class="{ done: seg.status === 'done' }">
            <span v-if="seg.status === 'running'" class="loading-icon"></span>
            <span v-else class="done-icon">✓</span>
            <span class="node-label">{{ seg.label }}</span>
          </div>
          <!-- 最终回复：黑色常展开 -->
          <div v-else-if="seg.role === 'answer'" class="markdown-body" v-html="renderMarkdown(seg.text)"></div>
          <!-- 中间推理：淡色，写完折叠 -->
          <div v-else class="reasoning-block">
            <div class="reasoning-head" @click="toggleReasoning(index, sIdx)">
              <span class="reasoning-caret">{{ isReasoningOpen(index, sIdx, seg) ? '▾' : '▸' }}</span>
              <span>{{ isReasoningOpen(index, sIdx, seg) ? '思考中…' : '已思考' }}</span>
            </div>
            <div v-if="isReasoningOpen(index, sIdx, seg)" class="reasoning-body markdown-body"
                 v-html="renderMarkdown(seg.text)"></div>
          </div>
        </template>
        <div v-if="inlineThinking(msg, index)" class="thinking-bubble">
          <span class="loading-icon"></span>
          <span>{{ thinkingLabel }}</span>
        </div>
      </div>
```

> 移除原 `v-if="msg.content"` 整块与 `clarify-options` 整块（澄清选项移至 ClarifyPanel）。

`<script setup>` 改动：新增 `displaySegments`（给每个 text 段动态标 role）、reasoning 折叠状态。
在现有 `import` 后加：

```ts
type DisplaySegment =
  | { kind: 'tool'; tool: string; label: string; status: 'running' | 'done' }
  | { kind: 'text'; text: string; role: 'reasoning' | 'answer' }

// 渲染期判定：最后一个 text 段为 answer，其余为 reasoning
const displaySegments = (msg: Message): DisplaySegment[] => {
  const segs = msg.segments ?? []
  let lastTextIdx = -1
  segs.forEach((s, i) => { if (s.kind === 'text') lastTextIdx = i })
  return segs.map((s, i) => {
    if (s.kind === 'tool') return s
    return { kind: 'text', text: s.text, role: i === lastTextIdx ? 'answer' : 'reasoning' }
  })
}

// 用户手动展开的 reasoning 段：键为 `${msgIdx}:${segIdx}`
const manuallyOpen = ref<Set<string>>(new Set())
const reasoningKey = (m: number, s: number) => `${m}:${s}`
const toggleReasoning = (m: number, s: number) => {
  const k = reasoningKey(m, s)
  const next = new Set(manuallyOpen.value)
  next.has(k) ? next.delete(k) : next.add(k)
  manuallyOpen.value = next
}
// 展开条件：用户手动展开，或它是最后一条消息里正在写入的最后一段（流式中）
const isReasoningOpen = (m: number, s: number, _seg: DisplaySegment): boolean => {
  if (manuallyOpen.value.has(reasoningKey(m, s))) return true
  if (!props.loading) return false
  if (m !== props.messages.length - 1) return false
  const segs = props.messages[m].segments ?? []
  return s === segs.length - 1 && segs[s]?.kind === 'text'
}
```

`inlineThinking` 判据从 `toolSteps` 改 `segments`：

```ts
const inlineThinking = (msg: Message, index: number) => {
  if (!props.loading) return false
  if (index !== props.messages.length - 1) return false
  if (msg.role !== 'assistant') return false
  const segs = msg.segments ?? []
  const last = segs[segs.length - 1]
  if (last && last.kind === 'text' && last.text) return false  // 正在出正文
  if (segs.some((s) => s.kind === 'tool' && s.status === 'running')) return false
  return true
}
```

移除 `import AgentProgress` 与 `clarify-answer` emit（若 ClarifyPanel 接管发送）。保留 `Message` import。
emit 定义可删除 `clarify-answer`（改由 ClarifyPanel 调 store/useSSE）。

- [ ] **Step 2: 加 reasoning/pill 样式**

在 `MessageList.vue` 的 `<style scoped>` 内追加（pill 样式从 AgentProgress 迁移过来）：

```css
.node-pill {
  display: inline-flex; align-items: center; padding: 6px 14px; margin: 4px 0;
  background-color: var(--el-fill-color-light, #f4f4f5);
  border: 1px solid var(--el-border-color-lighter, #e4e7ed);
  border-radius: 20px; font-size: 13px; color: var(--el-text-color-regular, #606266);
}
.node-pill.done { opacity: 0.7; background-color: var(--el-color-success-light-9, #f0f9eb);
  border-color: var(--el-color-success-light-7, #e1f3d8); }
.node-pill .node-label { line-height: 1; font-weight: 500; }
.node-pill .loading-icon { width: 12px; height: 12px; margin-right: 8px;
  border: 2px solid var(--el-color-primary, #409eff); border-top-color: transparent;
  border-radius: 50%; animation: spin 0.8s linear infinite; }
.node-pill .done-icon { width: 12px; height: 12px; margin-right: 8px;
  color: var(--el-color-success, #67c23a); font-weight: bold; line-height: 12px; text-align: center; }

.reasoning-block { margin: 6px 0; }
.reasoning-head { display: inline-flex; align-items: center; gap: 6px; cursor: pointer;
  color: var(--el-text-color-secondary, #909399); font-size: 13px; user-select: none; }
.reasoning-caret { font-size: 11px; }
.reasoning-body { color: var(--el-text-color-secondary, #909399); font-size: 13px;
  margin-top: 4px; padding-left: 14px; border-left: 2px solid var(--el-border-color-lighter, #e4e7ed); }
```

- [ ] **Step 3: 简化 AgentProgress（不再被 MessageList 引用）**

`AgentProgress.vue` 已无引用方。两条路任选其一，**推荐删除**以保持 DRY：
删除文件 `frontend/src/components/AgentProgress.vue`，并确认全仓无其它 import。

```bash
cd frontend && grep -rn "AgentProgress" src/ || echo "no refs"
```

若 `no refs`，删除该文件。

- [ ] **Step 4: 类型检查转绿**

Run: `cd frontend && bun run build`
Expected: PASS（vue-tsc 全绿，vite build 成功）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/MessageList.vue
git rm frontend/src/components/AgentProgress.vue
git commit -m "feat(ui): MessageList 顺序渲染 segments，reasoning 写完折叠

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: ClarifyPanel 浮层面板 + ChatPanel 挂载

新增输入框上方从下往上弹出的澄清浮层，含问题、选项按钮、自定义填写框；选择/提交后发出答案并关闭。

**Files:**
- Create: `frontend/src/components/ClarifyPanel.vue`
- Modify: `frontend/src/components/ChatPanel.vue`

**Interfaces:**
- Consumes: `tripStore.pendingClarify`、`tripStore.setPendingClarify`、`useSSE().send`。
- Produces: 选项/自定义答案经 `send` 发出，发出后 `setPendingClarify(null)`。

- [ ] **Step 1: 创建 ClarifyPanel.vue**

```vue
<template>
  <transition name="clarify-pop">
    <div v-if="clarify" class="clarify-panel">
      <div class="clarify-head">
        <span class="clarify-question">{{ clarify.question }}</span>
        <el-icon class="clarify-close" @click="close"><Close /></el-icon>
      </div>
      <div class="clarify-options">
        <el-button
          v-for="option in clarify.options"
          :key="option"
          size="small"
          plain
          :disabled="loading"
          @click="choose(option)"
        >{{ option }}</el-button>
      </div>
      <div class="clarify-custom">
        <el-input
          v-model="custom"
          size="small"
          placeholder="或填写其它答案…"
          :disabled="loading"
          @keydown.enter.prevent="submitCustom"
        />
        <el-button size="small" type="primary" :disabled="!custom.trim() || loading" @click="submitCustom">
          提交
        </el-button>
      </div>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Close } from '@element-plus/icons-vue'
import { useTripStore } from '../stores/trip'

const props = defineProps<{ loading: boolean }>()
const emit = defineEmits<{ (e: 'answer', text: string): void }>()

const tripStore = useTripStore()
const clarify = computed(() => tripStore.pendingClarify)
const custom = ref('')

const close = () => tripStore.setPendingClarify(null)

const choose = (option: string) => {
  if (props.loading) return
  tripStore.setPendingClarify(null)
  emit('answer', option)
}

const submitCustom = () => {
  const text = custom.value.trim()
  if (!text || props.loading) return
  custom.value = ''
  tripStore.setPendingClarify(null)
  emit('answer', text)
}
</script>

<style scoped>
.clarify-panel {
  position: absolute;
  left: 16px; right: 16px; bottom: 100%;
  margin-bottom: 8px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 10px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.12);
  padding: 12px 14px;
  z-index: 20;
}
.clarify-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
.clarify-question { font-size: 14px; color: #303133; font-weight: 500; line-height: 1.4; }
.clarify-close { cursor: pointer; color: #909399; flex-shrink: 0; margin-top: 2px; }
.clarify-options { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }
.clarify-custom { display: flex; gap: 8px; }

/* 从下往上弹出 */
.clarify-pop-enter-active, .clarify-pop-leave-active { transition: all 0.25s cubic-bezier(0.25, 0.8, 0.25, 1); }
.clarify-pop-enter-from, .clarify-pop-leave-to { opacity: 0; transform: translateY(16px); }
</style>
```

- [ ] **Step 2: ChatPanel 挂载浮层并接线**

在 `frontend/src/components/ChatPanel.vue` 模板里，把底部输入区包一层相对定位容器并插入面板。
把 `<ChatInput .../>` 替换为：

```vue
    <div class="input-area">
      <ClarifyPanel :loading="loading" @answer="send" />
      <ChatInput :loading="loading" @send="send" @abort="abort" />
    </div>
```

`<script setup>` 加 import：

```ts
import ClarifyPanel from './ClarifyPanel.vue'
```

`MessageList` 的 `@clarify-answer="send"` 监听移除（Task 7 已删该 emit）：把
`<MessageList :messages="tripStore.messages" :loading="loading" @clarify-answer="send" />`
改为 `<MessageList :messages="tripStore.messages" :loading="loading" />`。

`<style scoped>` 加：

```css
.input-area { position: relative; }
```

- [ ] **Step 3: 类型检查 + 构建**

Run: `cd frontend && bun run build`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/ClarifyPanel.vue frontend/src/components/ChatPanel.vue
git commit -m "feat(ui): 澄清浮层面板，输入框上方弹出含选项与自定义填写

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: 更新 AGENTS.md 安全约定与 SSE 契约说明

把「中间节点 token 不暴露前端」改为符合本次实现的描述。

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: 改安全约定条目**

把 `AGENTS.md` 「安全约定」节中：
```
- 中间节点的 LLM token 不暴露给前端，仅最终回复逐字流出。
```
改为：
```
- 中间推理文本随 `token` 事件流出前端，前端淡色展示、写完自动折叠为「已思考」；最终回复黑色常展开。中间节点的工具入参/原始结果不直接外发，仅经 `build_tool_label` 脱敏为中文进度文案。
```

- [ ] **Step 2: 提交**

```bash
git add AGENTS.md
git commit -m "docs: 更新中间推理流出与展示的安全约定

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: 后端全量回归 + 前端构建

确保全链路绿。

**Files:** 无（仅运行）

- [ ] **Step 1: 后端全量测试**

Run: `cd backend && uv run pytest -q`
Expected: 全部 PASS（无 failed）

- [ ] **Step 2: 前端构建**

Run: `cd frontend && bun run build`
Expected: vue-tsc 全绿，vite build 成功

- [ ] **Step 3: 若有失败，修复后重跑至全绿**

逐条定位修复，不跳过、不 xfail。

---

### Task 11: 改动记录文档

按项目规则在 `plan/` 写记录。

**Files:**
- Create: `plan/20260629_chat_interleave_and_clarify_panel/README.md`

- [ ] **Step 1: 写 README**

包含：任务目标、改动文件清单（表格）、改动详情（每个文件改了什么、为何）、测试结果
（后端 pytest 通过数、前端 build 结果）、相关讨论（segments 贯穿三路径的一致性决策、
中间推理流出对安全约定的调整、reasoning 写完折叠的判定规则）。

- [ ] **Step 2: 提交**

```bash
git add plan/20260629_chat_interleave_and_clarify_panel/README.md
git commit -m "docs: 交错渲染+澄清面板改动记录

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review 结论

**Spec 覆盖：**
- 交错渲染（需求 2）→ Task 1/3/4（后端 segments）+ Task 5/7（前端结构与渲染）。✓
- 淡色推理 + 黑色结论 → Task 7 `displaySegments` 渲染期判定。✓
- 推理输出展开、写完折叠 → Task 7 `isReasoningOpen`。✓
- 澄清浮层 + 选项 + 自定义填写（需求 1）→ Task 8 ClarifyPanel；选项移出气泡 → Task 7 移除 clarify-options。✓
- 实时与历史完全一致 → segments 贯穿 stream（Task 3）/ store（Task 5）/ session_store（Task 2）/ sessions 重建（Task 4）。✓
- 旧数据降级 → Task 2 `list_ui_messages`。✓
- 安全约定更新 → Task 9。✓
- 改动记录 → Task 11。✓

**占位符扫描：** 无 TBD/TODO；每个代码步骤含完整代码。✓

**类型一致性：** segment dict 形态（`kind`/`text`/`tool`/`label`/`status`）在 Task 1/2/3/4 一致；
前端 `Segment`（Task 5）与渲染 `DisplaySegment`（Task 7）字段一致；
store actions 名（`appendToken`/`startToolCall`/`endToolCall`/`setPendingClarify`）在 Task 5 定义、
Task 6/7/8 消费一致。✓
