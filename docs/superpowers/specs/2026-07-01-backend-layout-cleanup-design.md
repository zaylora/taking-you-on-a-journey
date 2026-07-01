# 后端目录归整设计（重构收尾 + 正名 + 分层显化）

- 日期：2026-07-01
- 范围：`backend/app/` 目录结构。**纯搬迁 + 改 import + 补文档，行为零变化**，不改任何业务逻辑、不改 SSE 契约、不改前端。
- 缘起：用户参考 [backend/AGENTS.md](../../../backend/AGENTS.md) 里那份「通用大型 Agent 平台」骨架，觉得当前后端「冗余、不够规范」。经查证，当前后端本身组织良好，真正问题是**上一轮 ReAct 重构没收尾**留下的疤痕（`graph/` 层）与个别**名不副实的目录**（`utils/`）。本设计据此归整，并按用户意愿把 `tools/` 显化为顶层能力层，同时用文档而非空壳来对齐骨架的「分层清晰」精神。

## 1. 诊断结论

### 1.1 `graph/` 层是重构疤痕

历史上 `app/graph/` 承载「16 节点固定编排图」。[2026-06-25 ReAct 重构](2026-06-25-react-agent-design.md) 后整张图坍缩为单个 `create_agent`，组装逻辑迁到 [agent/build.py](../../../backend/app/agent/build.py)。遗留：

- [graph/builder.py](../../../backend/app/graph/builder.py)（10 行）退化为**纯转发壳**：`build_graph()` 只是 `return build_trip_agent(...)`。无独立价值，仅因 `main.py` / `langgraph.json` / 测试引用旧签名而留存。
- [graph/stream.py](../../../backend/app/graph/stream.py)（244 行）是**核心 SSE 桥接层**，不冗余，但与「图」已无关系——它服务于 [api/chat.py](../../../backend/app/api/chat.py) 端点，本质是 API 传输层，挂在 `graph/` 下名不副实。

### 1.2 `utils/` 名不副实

[utils/amap.py](../../../backend/app/utils/amap.py) 是高德 Web 服务的**外部服务客户端**，`utils/` 目录仅此一文件。正名为 `clients/`，语义更准，为未来外部客户端预留归处。

### 1.3 `agent/` 内部不拆代码，用文档对齐骨架精神

骨架里的 `orchestrator / planner / executor / router` 是**手写 Agent 框架**才需要的组件。本项目用 LangGraph `create_agent`，这四件均由框架内建，**无真实代码可拆**：

| 骨架概念 | 本项目由谁承载 |
|---|---|
| orchestrator（总调度） | `create_agent` 本身（`agent/build.py` 组装它） |
| planner（LLM 任务拆解） | 模型 + system prompt（`agent/prompt.py`）；ReAct 每步由模型自行决策，无独立 planner |
| executor（工具执行） | `create_agent` 内建 ToolNode |
| router（tool routing） | `create_agent` 内建条件边 |
| state（状态机） | ✅ 已有 `agent/state.py`（`TripState`） |
| schema（内部结构） | ✅ 已有 `schemas/` + `agent/itinerary/schemas.py` |

新建这四个文件只会得到空壳或转发（新的冗余），违反 YAGNI 与 AGENTS.md「依赖优先原则」。因此**不新建任何 agent 子文件**，改为在 `backend/AGENTS.md` 写清上表映射，让读者一眼看懂「框架就是 orchestrator/planner/executor/router」。

### 1.4 明确不做（防过度工程）

- 不加 `middleware/` / `models/` / `repositories/` / `db/` / `queue/` / `memory/long_term`：无近期需求（无多用户/登录/异步队列/RAG），加了即空壳。保留为 backend/AGENTS.md 的「未来北极星」，按需再长出。
- 不做 `state.py` 裸 `dict/list`（`day_plans` / `budget_check`）强类型化：会牵动 `itinerary/`、`tools/`、前端数据契约，是独立且更高风险的任务，另开一轮设计。

## 2. 目标结构

```
backend/app/
├── main.py                 # import 改 2 处
├── api/
│   ├── chat.py             # 路由（改 1 行 import）
│   ├── chat_stream.py      # ← 原 graph/stream.py（SSE 桥接层）
│   └── sessions.py         # 不变
├── tools/                  # ← 原 agent/tools/（显化为顶层能力层）
│   ├── __init__.py
│   ├── budget.py / clarify.py / itinerary.py / lodging.py
│   ├── persisted_result.py / time.py / trip.py / xhs.py / utils.py
├── agent/                  # 「大脑」：保留框架组装、大脑资产与基建
│   ├── build.py            # ← 吸收 make_graph / build_graph；组装 create_agent
│   ├── state.py / prompt.py / reducers.py / time_context.py
│   ├── tool_result_storage.py  # 大工具结果落盘基建（tools 依赖它，方向 tools→agent）
│   └── itinerary/          # 纯计算编排算法（预算/路线/聚类/diff），不变
├── clients/                # ← 原 utils/（正名）
│   └── amap.py
├── core/ / llm/ / schemas/ / services/   # 不变
```

`graph/` 与 `utils/` 目录删除。

**依赖方向说明**：`app.tools.*` 会 import `app.agent.itinerary`（编排算法）、`app.agent.prompt`（如 `XHS_RESEARCH_SYS`）、`app.agent.time_context`（`current_time_payload`）、`app.agent.tool_result_storage`（落盘基建）。即能力层依赖大脑层的算法、资产与基建，方向为 `tools → agent`，可接受。`agent/build.py` 反向 import `app.tools`（工具清单），二者不构成循环（build 只在组装期引用 tools，tools 不引用 build）。

## 3. 改动清单

### 3.1 消除 `graph/`

| 动作 | 文件 |
|---|---|
| `graph/stream.py` 整体移动 → `api/chat_stream.py`（内容不变） | 新 `api/chat_stream.py`，删 `graph/stream.py` |
| `build_graph` / `make_graph` 移入 `agent/build.py`（内容不变） | `agent/build.py` |
| 删 `graph/builder.py` 与空的 `graph/`（含 `__init__.py`） | `graph/` |
| `api/chat.py`：`from app.graph.stream import sse_events` → `from app.api.chat_stream import sse_events` | `api/chat.py:6` |
| `main.py`：`from app.graph.builder import build_graph` → `from app.agent.build import build_graph` | `main.py:18` |
| `langgraph.json`：`"./app/graph/builder.py:make_graph"` → `"./app/agent/build.py:make_graph"` | `langgraph.json:4` |

**坑点**：`render_xhs_sources` 真正定义在 [services/message_history.py:12](../../../backend/app/services/message_history.py)，`stream.py` 仅转发。迁移后测试应改为从源头导入。

### 3.2 `utils/` → `clients/`

| 动作 | 文件 |
|---|---|
| `utils/amap.py` → `clients/amap.py`，新增 `clients/__init__.py` | 新 `clients/`，删 `utils/` |
| 三处业务引用 `from app.utils import amap` → `from app.clients import amap` | `agent/tools/trip.py:9`（迁移后为 `tools/trip.py`）、`tools/lodging.py:13`、`agent/itinerary/routing/matrix.py:10` |

### 3.3 `agent/tools/` → `app/tools/`（顶层能力层）

| 动作 | 文件 |
|---|---|
| `agent/tools/` 整个目录移动 → `app/tools/`（含 9 个工具模块 + `utils.py` + `__init__.py`，内容不变） | `app/tools/` |
| tools 内部对 `app.agent.*` 的 import **全部保持不变**（`tool_result_storage`、`prompt`、`time_context`、`itinerary.*` 均留在 agent/） | `tools/xhs.py:15,18`、`tools/persisted_result.py:6`、`tools/time.py:5`、`tools/itinerary.py:12-17`、`tools/budget.py:11-12`、`tools/lodging.py:9` |
| `agent/build.py`：`from app.agent.tools import (...)` → `from app.tools import (...)` | `agent/build.py:14` |

### 3.4 测试引用同步（最易漏，逐一列出）

| 文件 | 改动 |
|---|---|
| `tests/test_chat_stream.py:14` | `from app.graph.stream import sse_events` → `from app.api.chat_stream import sse_events` |
| `tests/test_chat_stream.py:29` | → `from app.services.message_history import render_xhs_sources` |
| `tests/agent/test_build_agent.py:19` | `from app.graph.builder import build_graph` → `from app.agent.build import build_graph` |
| `tests/test_amap.py:4` | `import app.utils.amap as amap` → `import app.clients.amap as amap` |
| `tests/test_amap.py:64` | `logger="app.utils.amap"` → `logger="app.clients.amap"`（**logger 名随模块路径变化，必须同步**） |
| `tests/conftest.py:58-59` | `import app.utils.amap as amap` → `import app.clients.amap as amap` |
| `tests/agent/test_matrix.py:39` | `"app.utils.amap.distance_batch"` → `"app.clients.amap.distance_batch"` |
| `tests/agent/test_tools.py:8` | `from app.agent import tools` → `from app import tools` |
| `tests/agent/test_tools.py:11` | `from app.agent.tools import xhs as xhs_tools` → `from app.tools import xhs as xhs_tools` |
| `tests/agent/test_tools.py`（约 14 处 monkeypatch 字符串路径） | `"app.agent.tools.trip.amap.search_poi"`→`"app.tools.trip.amap.search_poi"`（4 处）；`"app.agent.tools.itinerary.build_llm"`→`"app.tools.itinerary.build_llm"`（8 处）；`"app.agent.tools.lodging.build_llm"`→`"app.tools.lodging.build_llm"`（2 处） |

> 注：tools 迁移后，`tools/trip.py` 内 `amap` 的绑定路径变为 `app.tools.trip.amap`；monkeypatch 字符串必须整体跟随，否则打桩失效、测试会真实发起高德/LLM 调用而挂掉。

## 4. 测试策略

行为零变化，以「测试全绿」作为等价性证明：

1. `cd backend && uv run pytest -q` 全绿。重点盯 `test_tools.py`（monkeypatch 路径）、`test_chat_stream.py`、`test_build_agent.py`、`test_amap.py`、`test_matrix.py`、`conftest.py`。
2. 冒烟导入：`uv run python -c "import app.main; import app.api.chat_stream; import app.clients.amap; import app.tools; print('import OK')"`。
3. 残留旧路径检查：全仓 grep `app.graph`、`app.utils.amap`、`app.agent.tools`，在 `app/` 与 `tests/` 下须为零（历史 `docs/` / `plan/` 记录不改动）。注意 `app.agent.tool_result_storage` 仍在原位，不在清零之列。
4. LangGraph 平台入口：确认 `langgraph.json` 指向的 `app/agent/build.py:make_graph` 可加载。
5. 循环导入检查：确认 `app.agent.build` ↔ `app.tools` 无循环（build 组装期引用 tools，tools 不引用 build）。

## 5. 风险与回滚

- graph/ 与 clients/ 两块风险极低（纯路径迁移）。
- tools 提取风险中等：跨层依赖 + 约 16 处测试 monkeypatch 字符串路径，最易漏；由 pytest + grep 双重兜底。
- 建议**分两次提交**：①graph/ + clients/（低风险先落地）；②tools 提取（单独一提交，便于出错时精准 revert）。

## 6. 文档同步

- 更新根 [AGENTS.md](../../../AGENTS.md) 目录结构段：去 `graph/`，`utils/`→`clients/`，`api/` 增 `chat_stream.py`，`tools/` 提为顶层，`agent/` 说明只留组装与大脑资产。
- 更新 [backend/AGENTS.md](../../../backend/AGENTS.md)：加入 §1.3 的「骨架概念 → create_agent 内建」映射表；保留大平台骨架作为「未来北极星」并注明「当前为聚焦单 Agent 应用，按需长出分层，不预建空壳」。
- 在 `plan/20260701_backend_layout_cleanup/README.md` 记录本次改动（遵循项目改动记录规则）。
