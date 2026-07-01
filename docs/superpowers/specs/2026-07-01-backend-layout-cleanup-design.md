# 后端目录归整设计（重构收尾 + 正名）

- 日期：2026-07-01
- 范围：`backend/app/` 目录结构。**纯搬迁 + 改 import，行为零变化**，不改任何业务逻辑、不改 SSE 契约、不改前端。
- 缘起：用户参考 [backend/AGENTS.md](../../../backend/AGENTS.md) 里那份「通用大型 Agent 平台」骨架，觉得当前后端「冗余、不够规范」。经查证，当前后端本身组织良好，真正的问题是**上一轮 ReAct 重构没收尾**留下的疤痕组织（`graph/` 层）与个别**名不副实的目录**（`utils/`）。本设计只处理这两处，不引入任何企业级空壳层。

## 1. 诊断结论

### 1.1 `graph/` 层是重构疤痕

历史上 `app/graph/` 承载「16 节点固定编排图」。[2026-06-25 ReAct 重构](2026-06-25-react-agent-design.md) 后整张图坍缩为单个 `create_agent`，真正的组装逻辑迁到 [agent/build.py](../../../backend/app/agent/build.py)。遗留结果：

- [graph/builder.py](../../../backend/app/graph/builder.py)（10 行）退化为**纯转发壳**：`build_graph()` 只是 `return build_trip_agent(checkpointer)`，`make_graph()` 只是 `build_trip_agent(checkpointer=None)`。无独立价值，仅因 `main.py` / `langgraph.json` / 测试引用旧签名而留存。
- [graph/stream.py](../../../backend/app/graph/stream.py)（244 行）是**核心 SSE 桥接层**（`astream_events(v2) → SSE`），并不冗余，但与「图」已无关系——它服务于 [api/chat.py](../../../backend/app/api/chat.py) 端点，本质是 API 传输层，挂在 `graph/` 下名不副实。

### 1.2 `utils/` 名不副实

[utils/amap.py](../../../backend/app/utils/amap.py) 是高德 Web 服务的**外部服务客户端**，不是通用工具函数。`utils/` 目录当前仅此一个文件。正名为 `clients/`，语义更准，且为未来其他外部服务客户端预留归处。

### 1.3 明确不做（防过度工程）

以下均**不纳入本设计**，理由是无近期需求、加了即空壳，违反项目 AGENTS.md 的 YAGNI 原则：

- 不加 `middleware/`（横切能力当前由 FastAPI 内建 + create_agent middleware 承载）、`models/` / `repositories/` / `db/`（无传统 ORM，持久化走 SQLite checkpointer + SessionStore）、`queue/`（无异步长任务）、`memory/long_term`（无 RAG/向量库）。这些作为「未来北极星」保留在 backend/AGENTS.md，等真有需求再按需长出。
- 不拆 `agent/` 根目录的文件成子目录：数量不多、职责已清晰，分子目录只会加深 import 路径、牵动大量引用，得不偿失。
- 不做 `state.py` 裸 `dict/list`（`day_plans` / `budget_check` 等）的强类型化：会牵动 `itinerary/`、`tools/`、前端数据契约，是一次独立且风险更高的任务，另开一轮设计，不混入本次目录归整。

## 2. 目标结构

```
backend/app/
├── main.py                 # import 改 2 处
├── api/
│   ├── chat.py             # 路由（改 1 行 import）
│   ├── chat_stream.py      # ← 原 graph/stream.py（SSE 桥接层）
│   └── sessions.py         # 不变
├── agent/
│   ├── build.py            # ← 吸收 make_graph / build_graph
│   ├── state.py / prompt.py / reducers.py / time_context.py
│   ├── tool_result_storage.py
│   ├── tools/ / itinerary/ # 不变
├── clients/                # ← 原 utils/（正名）
│   └── amap.py
├── core/ / llm/ / schemas/ / services/   # 不变
```

`graph/` 目录删除（清空后移除）。

## 3. 改动清单

### 3.1 消除 `graph/`

| 动作 | 文件 |
|---|---|
| `graph/stream.py` 整体移动 → `api/chat_stream.py`（内容不变） | 新 `api/chat_stream.py`，删 `graph/stream.py` |
| `build_graph` / `make_graph` 两函数移入 `agent/build.py`（内容不变） | `agent/build.py` |
| 删除 `graph/builder.py`，删除空的 `graph/` 目录（含 `__init__.py`） | `graph/` |
| `api/chat.py`：`from app.graph.stream import sse_events` → `from app.api.chat_stream import sse_events` | `api/chat.py:6` |
| `main.py`：`from app.graph.builder import build_graph` → `from app.agent.build import build_graph` | `main.py:18` |
| `langgraph.json`：`"./app/graph/builder.py:make_graph"` → `"./app/agent/build.py:make_graph"` | `langgraph.json:4` |

**坑点**：`test_chat_stream.py:29` 现在从 `app.graph.stream` 导入 `render_xhs_sources`，但该函数真正定义在 [services/message_history.py:12](../../../backend/app/services/message_history.py)，`stream.py` 仅转发。迁移后测试应改为从源头导入：`from app.services.message_history import render_xhs_sources`（比继续依赖转发更干净）。`api/chat_stream.py` 内部对 `render_xhs_sources` 的既有 import 保持不变。

### 3.2 `utils/` → `clients/`

| 动作 | 文件 |
|---|---|
| `utils/amap.py` 移动 → `clients/amap.py`，新增 `clients/__init__.py` | 新 `clients/`，删 `utils/` |
| 三处业务引用 `from app.utils import amap` → `from app.clients import amap` | `agent/tools/trip.py:9`、`agent/tools/lodging.py:13`、`agent/itinerary/routing/matrix.py:10` |

### 3.3 测试引用同步

| 文件 | 改动 |
|---|---|
| `tests/test_chat_stream.py:14` | `from app.graph.stream import sse_events` → `from app.api.chat_stream import sse_events` |
| `tests/test_chat_stream.py:29` | → `from app.services.message_history import render_xhs_sources` |
| `tests/agent/test_build_agent.py:19` | `from app.graph.builder import build_graph` → `from app.agent.build import build_graph` |
| `tests/test_amap.py:4` | `import app.utils.amap as amap` → `import app.clients.amap as amap` |
| `tests/test_amap.py:64` | `caplog.set_level("INFO", logger="app.utils.amap")` → `logger="app.clients.amap"`（**logger 名随模块路径变化，必须同步**） |
| `tests/conftest.py:58-59` | `import app.utils.amap as amap` → `import app.clients.amap as amap` |
| `tests/agent/test_matrix.py:39` | `monkeypatch.setattr("app.utils.amap.distance_batch", ...)` → `"app.clients.amap.distance_batch"` |

## 4. 测试策略

行为零变化，以「测试全绿」作为等价性证明：

1. `cd backend && uv run pytest -q` 全绿。重点盯 `test_chat_stream.py`、`test_build_agent.py`、`test_amap.py`、`test_matrix.py`、`conftest.py` fixture 的 import 已更新。
2. 冒烟导入：`uv run python -c "import app.main; import app.api.chat_stream; import app.clients.amap; print('import OK')"`。
3. 确认再无残留旧路径引用：全仓 grep `app.graph`、`app.utils.amap` 应仅剩历史 `docs/`、`plan/` 记录（不改动历史文档），`app/` 与 `tests/` 下须为零。
4. LangGraph 平台入口：确认 `langgraph.json` 指向的 `app/agent/build.py:make_graph` 可被加载（`make_graph` 已迁入且签名不变）。

## 5. 风险与回滚

- 风险极低：无逻辑改动，纯路径迁移。最大风险是**漏改某处 import** 或 **logger 名不同步**，均由 pytest + grep 兜底。
- 回滚：单次提交，`git revert` 即可。

## 6. 文档同步

- 更新根 [AGENTS.md](../../../AGENTS.md) 目录结构段：去掉 `graph/`，`utils/` 改为 `clients/`，`api/` 增列 `chat_stream.py`。
- 在 `plan/20260701_backend_layout_cleanup/README.md` 记录本次改动（遵循项目改动记录规则）。
- 可在 backend/AGENTS.md 保留那份大平台骨架作为「未来北极星」，并加一句说明：当前为聚焦单 Agent 应用，按需长出分层，不预建空壳。
