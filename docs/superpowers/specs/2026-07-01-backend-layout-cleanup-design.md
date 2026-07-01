# 后端目录归整设计（重构收尾 + 能力层三分层）

- 日期：2026-07-01
- 范围：`backend/app/` 目录结构。**纯搬迁 + 改 import + 补文档，行为零变化**，不改任何业务逻辑、不改 SSE 契约、不改前端。
- 缘起：用户参考 [backend/AGENTS.md](../../../backend/AGENTS.md) 那份「通用大型 Agent 平台」骨架，觉得后端「冗余、不够规范」。经查证，后端本身组织良好，真正问题是**上一轮 ReAct 重构没收尾**（`graph/` 疤痕层）与**能力相关代码分散**（`agent/tools/`、`agent/itinerary/`、`utils/amap.py` 各在一处）。本设计：①消除 `graph/`；②把工具能力域统一到顶层 `tools/`，内部按角色分 `actions/planning/clients` 三层；③用文档而非空壳对齐骨架的「分层清晰」精神。

## 1. 诊断结论

### 1.1 `graph/` 层是重构疤痕

历史上 `app/graph/` 承载「16 节点固定编排图」。[2026-06-25 ReAct 重构](2026-06-25-react-agent-design.md) 后整张图坍缩为单个 `create_agent`，组装逻辑迁到 `agent/build.py`。遗留：

- `graph/builder.py`（10 行）退化为**纯转发壳**（`build_graph()` 只是 `return build_trip_agent(...)`），仅因 `main.py` / `langgraph.json` / 测试引用旧签名而留存。
- `graph/stream.py`（244 行）是**核心 SSE 桥接层**，不冗余，但与「图」已无关系——它服务于 `api/chat.py` 端点，本质是 API 传输层，挂在 `graph/` 下名不副实。

### 1.2 工具能力域分散在三处

当前"工具相关"的代码分散：`agent/tools/`（`@tool` 能力入口）、`agent/itinerary/`（纯计算领域算法：VRP 路线、预算、diff、聚类）、`utils/amap.py`（高德外部客户端）。三者角色不同但同属"工具能力域"，应统一到顶层 `tools/`，内部按角色分层。

**硬约束**：现有 `@tool` 模块名 `itinerary.py`、`lodging.py` 与算法包 `itinerary/`、算法文件 `lodging.py` 会撞名——Python 不允许同目录下 `itinerary.py` 与 `itinerary/` 并存。因此**必须按角色分子目录**（`actions/` 放 `@tool`、`planning/` 放算法），不能平铺。

### 1.3 `agent/` 内部不拆代码，用文档对齐骨架精神

骨架的 `orchestrator / planner / executor / router` 是**手写 Agent 框架**才需要的组件；本项目用 LangGraph `create_agent`，这四件由框架内建，**无真实代码可拆**：

| 骨架概念 | 本项目由谁承载 |
|---|---|
| orchestrator（总调度） | `create_agent` 本身（`agent/build.py` 组装它） |
| planner（LLM 任务拆解） | 模型 + system prompt（`agent/prompt.py`）；ReAct 每步由模型自行决策 |
| executor（工具执行） | `create_agent` 内建 ToolNode |
| router（tool routing） | `create_agent` 内建条件边 |
| state（状态机） | ✅ `agent/state.py`（`TripState`） |
| schema（内部结构） | ✅ `schemas/` + `tools/planning/schemas.py` |

新建这四个文件只会得到空壳（新冗余），违反 YAGNI 与 AGENTS.md「依赖优先原则」。改为在 `backend/AGENTS.md` 写清上表映射。

### 1.4 明确不做（防过度工程）

- 不加 `middleware/` / `models/` / `repositories/` / `db/` / `queue/` / `memory/long_term`：无近期需求，加了即空壳。保留为「未来北极星」。
- 不做 `state.py` 裸 `dict/list`（`day_plans` / `budget_check`）强类型化：牵动数据契约，另开一轮。
- 不拆 `agent/prompt.py`：`ITINERARY_SYS` / `ACCOMMODATION_SYS` / `XHS_RESEARCH_SYS` 等工具专用提示暂留 `prompt.py`，由 `tools/*` 依赖（`tools → agent.prompt`）。彻底自洽需下沉提示词，列为可选后续，本次不做。

## 2. 目标结构

```
backend/app/
├── main.py                     # import 改 1 处
├── api/
│   ├── chat.py                 # 路由（改 1 行 import）
│   ├── chat_stream.py          # ← 原 graph/stream.py（SSE 桥接层）
│   └── sessions.py             # 不变
├── tools/                      # 能力层大伞（新顶层）
│   ├── __init__.py             # 聚合并对 agent 暴露 @tool 清单
│   ├── actions/                # ← 原 agent/tools/：@tool（agent 直接调用）
│   │   ├── __init__.py
│   │   ├── budget.py / clarify.py / itinerary.py / lodging.py
│   │   ├── persisted_result.py / time.py / trip.py / xhs.py / utils.py
│   ├── planning/               # ← 原 agent/itinerary/：领域算法（纯计算）
│   │   ├── __init__.py
│   │   ├── budgeting.py / diffing.py / fill.py / lodging.py / schemas.py
│   │   └── routing/{__init__,assembler,matrix,optimizer,prefilter}.py
│   └── clients/                # ← 原 utils/：外部服务客户端
│       ├── __init__.py
│       └── amap.py
├── agent/                      # 「大脑」：框架组装 + 大脑资产 + 基建
│   ├── build.py                # ← 吸收 make_graph / build_graph；组装 create_agent
│   ├── state.py / prompt.py / reducers.py / time_context.py
│   └── tool_result_storage.py  # 大工具结果落盘基建（agent 基建，tools 依赖它）
├── core/ / llm/ / schemas/ / services/   # 不变
```

`graph/`、`utils/`、`agent/tools/`、`agent/itinerary/` 目录消失。

**依赖方向**（均为 `tools → agent`，无循环）：
- `tools/actions/*` → `tools/planning/*`（算法）、`tools/clients/*`（客户端）、`agent/prompt`（`XHS_RESEARCH_SYS`）、`agent/time_context`（`current_time_payload`）、`agent/tool_result_storage`（落盘）。
- `tools/planning/*` → `agent/prompt`（`ITINERARY_SYS`/`ACCOMMODATION_SYS`）、`tools/clients/amap`（`routing/matrix.py`）、`tools/planning` 内部互引。
- `agent/build.py` → `tools`（组装期引用 @tool 清单）。tools 不引用 build，无循环。

## 3. 改动清单

### 3.1 消除 `graph/`（提交①）

| 动作 | 位置 |
|---|---|
| `graph/stream.py` → `api/chat_stream.py`（内容不变） | 新 `api/chat_stream.py`，删 `graph/stream.py` |
| `build_graph` / `make_graph` 移入 `agent/build.py`（原样追加，调用同文件 `build_trip_agent`） | `agent/build.py` |
| 删 `graph/builder.py` 与空的 `graph/`（含 `__init__.py`） | `graph/` |
| `api/chat.py:6`：`from app.graph.stream import sse_events` → `from app.api.chat_stream import sse_events` | `api/chat.py` |
| `main.py:18`：`from app.graph.builder import build_graph` → `from app.agent.build import build_graph`（`main.py:48` 调用不变） | `main.py` |
| `langgraph.json:4`：`"./app/graph/builder.py:make_graph"` → `"./app/agent/build.py:make_graph"` | `langgraph.json` |

**坑点**：`render_xhs_sources` 真正定义在 `services/message_history.py:12`，`stream.py` 仅转发。测试改从源头导入。

### 3.2 建立 `tools/` 三层并迁移（提交②，原子）

> 中间态无法通过测试（三层互引），本提交须一次性完成所有搬迁 + import 重接，末尾统一跑全套测试。
>
> 注：`actions/` 内部对 `utils.py` 用的是**相对 import**（`from .utils import parse_jsonish_string`，见 `lodging.py:15`、`itinerary.py:21`），整目录 `git mv` 后 `.utils` 仍指向同级模块，**自动有效、无需改动**。下方 import 重接清单只列跨目录的绝对 import。

**目录搬迁**（`git mv` 保留历史）：

| 从 | 到 |
|---|---|
| `agent/tools/`（全部模块 + `__init__.py` + `utils.py`） | `tools/actions/` |
| `agent/itinerary/`（全部模块 + `routing/`） | `tools/planning/` |
| `utils/amap.py`、`utils/__init__.py` | `tools/clients/amap.py`、`tools/clients/__init__.py` |
| 新建 `tools/__init__.py`（聚合层，见下） | — |

**`tools/__init__.py`**（复制原 `agent/tools/__init__.py`，import 源改为 `app.tools.actions.*`）：

```python
# -*- coding: utf-8 -*-
"""ReAct Agent tool exports."""
from app.tools.actions.budget import compute_budget_tool, finalize_plan
from app.tools.actions.clarify import ask_clarification
from app.tools.actions.itinerary import assemble_itinerary
from app.tools.actions.lodging import assign_hotels
from app.tools.actions.persisted_result import read_persisted_tool_result
from app.tools.actions.time import get_current_time
from app.tools.actions.trip import (
    get_weather, plan_route, search_attractions, search_restaurants,
)
from app.tools.actions.xhs import (
    research_xhs_travel_guide, xhs_hot_notes, xhs_note_comments, xhs_read_note,
    xhs_search_notes, xhs_status, xhs_user_profile,
)

__all__ = [
    "get_current_time", "search_attractions", "search_restaurants", "get_weather",
    "plan_route", "assemble_itinerary", "assign_hotels", "read_persisted_tool_result",
    "compute_budget_tool", "finalize_plan", "ask_clarification", "xhs_status",
    "research_xhs_travel_guide", "xhs_search_notes", "xhs_read_note",
    "xhs_note_comments", "xhs_hot_notes", "xhs_user_profile",
]
```

**`tools/actions/*` 内部 import 重接**：

| 文件 | 原 | 新 |
|---|---|---|
| `actions/itinerary.py:12-17` | `from app.agent.itinerary.fill/schemas/routing.* import ...` | `from app.tools.planning.fill/schemas/routing.* import ...` |
| `actions/budget.py:11-12` | `from app.agent.itinerary.budgeting/diffing import ...` | `from app.tools.planning.budgeting/diffing import ...` |
| `actions/lodging.py:9` | `from app.agent.itinerary.lodging import ...` | `from app.tools.planning.lodging import ...` |
| `actions/lodging.py:13` | `from app.utils import amap` | `from app.tools.clients import amap` |
| `actions/trip.py:9` | `from app.utils import amap` | `from app.tools.clients import amap` |
| `actions/xhs.py:15,18` | `from app.agent.tool_result_storage / app.agent.prompt` | **保持不变**（二者仍在 agent/） |
| `actions/time.py:5` | `from app.agent.time_context import ...` | **保持不变** |
| `actions/persisted_result.py:6` | `from app.agent.tool_result_storage import ...` | **保持不变** |

**`tools/planning/*` 内部 import 重接**：

| 文件 | 原 | 新 |
|---|---|---|
| `planning/schemas.py:5` | `from app.agent.prompt import ITINERARY_SYS` | **保持不变** |
| `planning/lodging.py:5` | `from app.agent.prompt import ACCOMMODATION_SYS` | **保持不变** |
| `planning/lodging.py:6` | `from app.agent.itinerary.schemas import Hotel` | `from app.tools.planning.schemas import Hotel` |
| `planning/fill.py:12` | `from app.agent.itinerary.schemas import DayPlans` | `from app.tools.planning.schemas import DayPlans` |
| `planning/routing/matrix.py:10` | `from app.utils import amap` | `from app.tools.clients import amap` |

**`agent/build.py:14`**：`from app.agent.tools import (...)` → `from app.tools import (...)`（导入的 @tool 名不变）。

### 3.3 测试引用同步（提交②内，最易漏，逐一列出）

| 文件:行 | 改动 |
|---|---|
| `test_chat_stream.py:14` | `from app.graph.stream` → `from app.api.chat_stream`（属提交①） |
| `test_chat_stream.py:29` | `→ from app.services.message_history import render_xhs_sources`（属提交①） |
| `test_build_agent.py:19` | `from app.graph.builder import build_graph` → `from app.agent.build import build_graph`（属提交①） |
| `test_budgeting.py:1` | `app.agent.itinerary.budgeting` → `app.tools.planning.budgeting` |
| `test_lodging.py:1` | `app.agent.itinerary.lodging` → `app.tools.planning.lodging` |
| `test_itinerary_schemas.py:1` | `app.agent.itinerary.schemas` → `app.tools.planning.schemas` |
| `test_itinerary_fill.py:2` | `app.agent.itinerary.fill` → `app.tools.planning.fill` |
| `test_diffing.py:1` | `app.agent.itinerary.diffing` → `app.tools.planning.diffing` |
| `test_matrix.py:3` | `from app.agent.itinerary.routing import matrix` → `from app.tools.planning.routing import matrix` |
| `test_matrix.py:39` | `"app.utils.amap.distance_batch"` → `"app.tools.clients.amap.distance_batch"` |
| `test_optimizer.py:1-3` | `app.agent.itinerary.routing.*` → `app.tools.planning.routing.*` |
| `test_tools.py:8` | `from app.agent import tools` → `from app import tools` |
| `test_tools.py:11` | `from app.agent.tools import xhs` → `from app.tools.actions import xhs` |
| `test_tools.py:12` | `app.agent.itinerary.schemas` → `app.tools.planning.schemas` |
| `test_tools.py:13` | `app.agent.itinerary.lodging import _AccoResult` → `app.tools.planning.lodging` |
| `test_tools.py`（monkeypatch 字符串，14 处） | `"app.agent.tools.trip.amap.search_poi"`→`"app.tools.actions.trip.amap.search_poi"`（4）；`"app.agent.tools.itinerary.build_llm"`→`"app.tools.actions.itinerary.build_llm"`（8）；`"app.agent.tools.lodging.build_llm"`→`"app.tools.actions.lodging.build_llm"`（2） |
| `test_amap.py:4` | `import app.utils.amap as amap` → `import app.tools.clients.amap as amap` |
| `test_amap.py:64` | `logger="app.utils.amap"` → `logger="app.tools.clients.amap"`（**logger 名随模块路径，必须同步**） |
| `conftest.py:58-59` | `import app.utils.amap as amap` → `import app.tools.clients.amap as amap` |

> monkeypatch 字符串路径打桩若漏改，会失效并真实发起高德/LLM 调用而挂测试——是最需逐一核对的地方。

### 3.4 文档同步（提交③）

- 根 [AGENTS.md](../../../AGENTS.md) 目录段：去 `graph/`；`api/` 增 `chat_stream.py`；新增 `tools/`（`actions/planning/clients`）；`agent/` 说明只留组装、大脑资产、基建；删 `utils/`。
- [backend/AGENTS.md](../../../backend/AGENTS.md)：加入 §1.3 映射表；保留大平台骨架作「未来北极星」并注明「当前为聚焦单 Agent 应用，按需长出分层，不预建空壳」。
- 新建 `plan/20260701_backend_layout_cleanup/README.md`（遵循改动记录规则）。

## 4. 测试策略

行为零变化，以「测试全绿」作为等价性证明：

1. `cd backend && uv run pytest -q` 全绿。重点盯 `test_tools.py`（monkeypatch 路径）、`test_amap.py`（logger 名）、及 8 个 itinerary/routing 相关测试的 import。
2. 冒烟导入：`uv run python -c "import app.main; import app.api.chat_stream; import app.tools; import app.tools.planning.routing.optimizer; import app.tools.clients.amap; print('import OK')"`。
3. 残留旧路径检查：全仓 grep `app.graph`、`app.utils`、`app.agent.tools`、`app.agent.itinerary`，在 `app/` 与 `tests/` 下须为零（`app.agent.tool_result_storage`、`app.agent.prompt`、`app.agent.time_context` 仍在原位，不清零；历史 `docs/`/`plan/` 记录不改）。
4. LangGraph 平台入口：`langgraph.json` 指向的 `app/agent/build.py:make_graph` 可加载。
5. 循环导入：确认 `app.agent.build` ↔ `app.tools` 无循环。

## 5. 风险与回滚

- 提交①（graph/）风险低，纯路径迁移。
- 提交②（tools 三层）风险中：跨越约 12 个测试文件 + 三层互引 + 14 处 monkeypatch 字符串，是本次最大的一块。必须原子完成、末尾全套 pytest 兜底；出错 `git revert` 整个提交②即可回到干净态。
- 分三次提交，边界清晰，便于精准回滚。

## 6. 后续可选（本次不做）

- 把工具专用提示 `ITINERARY_SYS` / `ACCOMMODATION_SYS` / `XHS_RESEARCH_SYS` 从 `agent/prompt.py` 下沉到 `tools/`，消除 `tools → agent.prompt` 残余依赖，使 `tools` 完全自洽。
- `state.py` 裸 `dict/list` 强类型化。
