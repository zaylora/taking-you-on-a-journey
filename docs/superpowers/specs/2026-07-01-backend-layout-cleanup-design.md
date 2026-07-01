# 后端目录归整设计（重构收尾 + 能力层三分层）

- 日期：2026-07-01
- 范围：`backend/app/` 目录结构 + 一处横切能力中间件化。分两类工作，边界清晰：
  - **A. 目录归整（提交①②③）**：纯搬迁 + 改 import + 补文档，**行为零变化**，以「测试全绿=等价」验证。
  - **B. 落盘中间件化（提交④）**：**一处行为变更**——把「大工具结果落盘」从 xhs 单点手动，提升为拦截所有工具的 middleware。需 TDD 新测试，不能用等价性验证。
- 不改 SSE 契约、不改前端。
- 缘起：用户参考 [backend/AGENTS.md](../../../backend/AGENTS.md) 那份「通用大型 Agent 平台」骨架，觉得后端「冗余、不够规范」。经查证，后端本身组织良好，真正问题是**上一轮 ReAct 重构没收尾**（`graph/` 疤痕层）与**能力相关代码分散**（`agent/tools/`、`agent/itinerary/`、`utils/amap.py` 各在一处）。本设计：①消除 `graph/`；②把工具能力域统一到顶层 `tools/`（`actions/planning/clients` 三层）；③用文档而非空壳对齐骨架的「分层清晰」精神；④把散落的大结果落盘统一为 `wrap_tool_call` 中间件（横切能力归位，呼应骨架 `middleware/` 语义，但只建真实需要的一个）。

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

> 概念区分：骨架 `router.py` 指 **tool routing**（决定调哪个工具），由 `create_agent` 内建，不手写；本项目 `tools/registry.py` 做的是 **工具编目**（集中声明工具清单并暴露给组装），两者不是一回事，registry 不承担运行时路由。

### 1.4 明确不做（防过度工程）

- 不加 `models/` / `repositories/` / `db/` / `queue/` / `memory/long_term`：无近期需求，加了即空壳。保留为「未来北极星」。
- `middleware/`（与 `agent/` 并排）**会建**，但只放真实使用的中间件（`current_time` 迁入、`tool_result_persistence` 新增），不预留空文件。
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
│   ├── __init__.py             # 暴露注册中心（from registry import ALL_TOOLS）
│   ├── registry.py             # 工具注册中心：集中声明 @tool 清单（ALL_TOOLS）
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
│   ├── build.py                # ← 吸收 make_graph / build_graph；组装 create_agent；挂载 middleware
│   ├── state.py / prompt.py / reducers.py
│   ├── time_context.py         # 保留 current_time_payload / build_system_prompt / CurrentTimeArgs（供 time 工具与 middleware 复用）
│   └── tool_result_storage.py  # 大结果落盘基建（新增 persist_tool_content）
├── middleware/                 # 中间件层（与 agent 并排，横切能力）
│   ├── __init__.py
│   ├── current_time.py         # ← 迁自 agent/time_context.py 的 CurrentTimePromptMiddleware（提交③，等价搬迁）
│   └── tool_result_persistence.py  # ← 新增（提交③）：ToolResultPersistenceMiddleware（行为变更）
├── core/ / llm/ / schemas/ / services/   # 不变
```

`graph/`、`utils/`、`agent/tools/`、`agent/itinerary/` 目录消失。

**依赖方向**（均为 `tools → agent`，无循环）：
- `tools/actions/*` → `tools/planning/*`（算法）、`tools/clients/*`（客户端）、`agent/prompt`（`XHS_RESEARCH_SYS`）、`agent/time_context`（`current_time_payload`）、`agent/tool_result_storage`（提交③后 xhs 不再直接依赖，见 §3.4）。
- `tools/planning/*` → `agent/prompt`（`ITINERARY_SYS`/`ACCOMMODATION_SYS`）、`tools/clients/amap`（`routing/matrix.py`）、`tools/planning` 内部互引。
- `agent/build.py` → `tools`（`ALL_TOOLS`）、`middleware`（`CurrentTimePromptMiddleware` / `ToolResultPersistenceMiddleware`）。`middleware/*` → `agent/time_context`（`build_system_prompt`）、`agent/tool_result_storage`（`persist_tool_content`）、`core/config`。tools/agent 不反向引用 middleware，无循环。

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

**`tools/registry.py`**（新建，工具注册中心——集中 import 原 `agent/tools/__init__.py` 的 @tool 并声明清单，import 源改为 `app.tools.actions.*`）：

```python
# -*- coding: utf-8 -*-
"""工具注册中心：集中声明所有 @tool，统一暴露给 agent 组装。新增工具在此登记一处。"""
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

# agent 组装时的完整工具清单（顺序沿用原 build.py 的 _TOOLS，行为不变）。
ALL_TOOLS = [
    get_current_time, search_attractions, search_restaurants, get_weather, plan_route,
    assemble_itinerary, assign_hotels, compute_budget_tool, finalize_plan,
    ask_clarification, read_persisted_tool_result,
    xhs_status, research_xhs_travel_guide, xhs_search_notes, xhs_read_note,
    xhs_note_comments, xhs_hot_notes, xhs_user_profile,
]
```

**`tools/__init__.py`**（新建，能力域入口，对外暴露注册中心）：

```python
# -*- coding: utf-8 -*-
"""tools 能力域入口：从注册中心暴露工具清单。"""
from app.tools.registry import ALL_TOOLS

__all__ = ["ALL_TOOLS"]
```

**`agent/build.py`：用注册中心消除 `_TOOLS` 双写冗余**。删除原第 14-29 行的 18 个工具 import 块与 `_TOOLS = [...]` 列表，替换为 `from app.tools import ALL_TOOLS`；`create_agent(...)` 的 `tools=_TOOLS` 改为 `tools=ALL_TOOLS`。其余（`prompt` / `state` / `time_context` / `llm.factory` 的 import 与 middleware 逻辑）不变。

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

**`agent/build.py`** 的 tools 引用改动见上「用注册中心消除 `_TOOLS` 双写冗余」段。

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

### 3.4 建立 `middleware/` 目录并中间件化（提交③）

本提交建立与 `agent/` 并排的 `middleware/` 目录，含两部分：**(A) `CurrentTimePromptMiddleware` 迁入（等价搬迁）** 与 **(B) 落盘中间件新增（行为变更）**。

#### 3.4.A 迁入 `CurrentTimePromptMiddleware`（等价，零行为变化）

| 动作 | 位置 |
|---|---|
| 从 `agent/time_context.py` 移出 `CurrentTimePromptMiddleware` 类 → `middleware/current_time.py`（内容不变，`from app.agent.time_context import build_system_prompt` 引用其保留的构造函数） | 新 `middleware/current_time.py` |
| `agent/time_context.py` 保留 `current_time_payload` / `build_system_prompt` / `CurrentTimeArgs` / `WEEKDAYS`（`time` 工具与 middleware 复用），仅删去 middleware 类与其 `AgentMiddleware`/`ModelRequest` import | `agent/time_context.py` |
| `agent/build.py`：`from app.agent.time_context import CurrentTimePromptMiddleware` → `from app.middleware.current_time import CurrentTimePromptMiddleware` | `agent/build.py` |
| 新建 `middleware/__init__.py` | `middleware/` |

#### 3.4.B 落盘中间件（行为变更）

**目标**：把「大工具结果落盘」从 xhs 单点手动（`_maybe_persist_xhs_result`）提升为拦截所有工具的 `wrap_tool_call` 中间件。阈值复用 config 现有 `tool_result_persist_threshold_chars(20_000)` / `tool_result_preview_chars(2_000)` / `tool_result_storage_dir`，故对超大结果的落盘触发点与现状等价。

**行为变更点**（需知情）：
- 现状：仅 xhs 系工具返回前手动落盘，落盘对象是工具返回的 **dict**，envelope 作为返回值。
- 变更后：**所有非豁免工具**的超阈值结果都会被落盘；落盘对象是 **ToolMessage.content（已序列化文本）**，envelope 作为 content 字符串。模型看到的预览/hint 结构一致，`read_persisted_tool_result` 分页读取不受影响。

**豁免工具**（`_EXCLUDE`，不落盘）：`finalize_plan`、`compute_budget_tool`（短且有业务语义，需完整留给模型/前端，与 `ContextEditingMiddleware.exclude_tools` 一致）；`read_persisted_tool_result`（读回落盘内容，落盘会二次落盘）；`ask_clarification`（澄清短、需原样）。

**多态返回处理**（关键）：本项目工具两类返回——只读工具返回 dict/值（ToolNode 包成 `ToolMessage`），写 state 工具返回 `Command(update={"messages":[ToolMessage,...], ...})`。`wrap_tool_call` 的 `response` 因此是 `ToolMessage | Command`，两条路径都要处理：`ToolMessage` 直接改 `.content`；`Command` 在 `update["messages"]` 定位 `ToolMessage` 原地替换其 `.content`（其余 update 字段不动）。

**新增 `tool_result_storage.persist_tool_content`**（面向已序列化 content 的落盘；与 `maybe_persist_tool_result` 共用落盘核心 `_write_result_file`，避免重复）：

```python
def persist_tool_content(
    content: Any, *, tool_name: str, tool_call_id: str,
    storage_dir: str | Path, threshold_chars: int, preview_chars: int,
) -> str | None:
    """content 归一化为文本；超阈值则落盘并返回 envelope JSON 字符串，否则返回 None（不改）。"""
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)
    if len(text) <= threshold_chars:
        return None
    result_id = _write_result_file(text, tool_name=tool_name, tool_call_id=tool_call_id, storage_dir=storage_dir)
    return json.dumps({
        "ok": True, "persisted": True, "tool_name": tool_name, "result_id": result_id,
        "original_chars": len(text), "preview": text[:max(0, preview_chars)],
        "hint": "完整工具结果已落盘；如需原文，调用 read_persisted_tool_result 按 offset/limit 分页读取。",
    }, ensure_ascii=False)
```

**新增 `middleware/tool_result_persistence.py`**：

```python
# -*- coding: utf-8 -*-
"""中间件：大工具结果落盘（横切能力）。"""
from typing import Any
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.agent.tool_result_storage import persist_tool_content
from app.core.config import get_settings

_EXCLUDE = frozenset({
    "finalize_plan", "compute_budget_tool", "read_persisted_tool_result", "ask_clarification",
})


class ToolResultPersistenceMiddleware(AgentMiddleware):
    """拦截工具返回，对超阈值结果落盘并替换为轻量 envelope。"""

    def _apply(self, tool_name: str, response: Any) -> Any:
        if tool_name in _EXCLUDE:
            return response
        s = get_settings()
        kw = dict(
            tool_name=tool_name,
            storage_dir=s.tool_result_storage_dir,
            threshold_chars=s.tool_result_persist_threshold_chars,
            preview_chars=s.tool_result_preview_chars,
        )
        if isinstance(response, ToolMessage):
            new = persist_tool_content(response.content, tool_call_id=response.tool_call_id or "", **kw)
            return response if new is None else response.model_copy(update={"content": new})
        if isinstance(response, Command) and isinstance(response.update, dict):
            msgs = response.update.get("messages") or []
            for i, m in enumerate(msgs):
                if isinstance(m, ToolMessage):
                    new = persist_tool_content(m.content, tool_call_id=m.tool_call_id or "", **kw)
                    if new is not None:
                        msgs[i] = m.model_copy(update={"content": new})
        return response

    def wrap_tool_call(self, request, handler):
        return self._apply(request.tool.name, handler(request))

    async def awrap_tool_call(self, request, handler):
        return self._apply(request.tool.name, await handler(request))
```

**挂载到 `agent/build.py`**：`from app.middleware.tool_result_persistence import ToolResultPersistenceMiddleware`；`_build_context_middleware()` 列表加入 `ToolResultPersistenceMiddleware()`，置于 `CurrentTimePromptMiddleware()` 之后、`ContextEditingMiddleware(...)` 之前。

**移除 xhs 手动落盘**：删除 `tools/actions/xhs.py` 的 `_maybe_persist_xhs_result` 定义及其全部调用点（改为直接返回原始 result），移除 `from app.agent.tool_result_storage import maybe_persist_tool_result` import。落盘统一由 middleware 负责。（`maybe_persist_tool_result` 若无其它调用方，保留供既有单测 `test_tool_result_storage.py` 覆盖，不删除。）

**测试（TDD 新增 `tests/middleware/test_tool_result_persistence.py`；`CurrentTimePromptMiddleware` 迁移后同步 `tests/` 中对其的 import 路径，如有）**，先写红、后实现：
- 超阈值 `ToolMessage` → content 替换为含 `result_id` 的 envelope，文件落盘。
- 低于阈值 `ToolMessage` → 原样返回。
- 超阈值 `Command`（update.messages 含 ToolMessage）→ 该 ToolMessage.content 被替换，其余 update 字段不变。
- 豁免工具（如 `finalize_plan`）超阈值 → 不落盘、原样。
- envelope 可被 `read_persisted_tool_result_slice` 读回（result_id 有效）。
- async `awrap_tool_call` 路径行为同 sync。

### 3.5 文档同步（提交④）

- 根 [AGENTS.md](../../../AGENTS.md) 目录段：去 `graph/`；`api/` 增 `chat_stream.py`；新增 `tools/`（`actions/planning/clients`）；`agent/` 说明留组装、大脑资产、基建、`middleware.py`；删 `utils/`。
- [backend/AGENTS.md](../../../backend/AGENTS.md)：加入 §1.3 映射表；保留大平台骨架作「未来北极星」并注明「当前为聚焦单 Agent 应用，按需长出分层，不预建空壳」。
- AGENTS.md 安全约定/工具约定处补一句：大工具结果落盘现由 `ToolResultPersistenceMiddleware` 统一处理（原 xhs 手动落盘已下线）。
- 新建 `plan/20260701_backend_layout_cleanup/README.md`（遵循改动记录规则）。

## 4. 测试策略

提交①②④与 §3.4.A 为等价搬迁，以「测试全绿」为等价证明；提交③.B 落盘中间件为行为变更，走 TDD（先红后绿）+ 全套回归。

1. `cd backend && uv run pytest -q` 全绿。重点盯 `test_tools.py`（monkeypatch 路径）、`test_amap.py`（logger 名）、8 个 itinerary/routing 测试的 import、及新增 `test_tool_result_persistence.py`。
2. 冒烟导入：`uv run python -c "import app.main; import app.api.chat_stream; import app.tools; import app.tools.planning.routing.optimizer; import app.tools.clients.amap; import app.middleware.current_time; import app.middleware.tool_result_persistence; print('import OK')"`。
3. 残留旧路径检查：全仓 grep `app.graph`、`app.utils`、`app.agent.tools`、`app.agent.itinerary`，在 `app/` 与 `tests/` 下须为零；`app.agent.time_context import CurrentTimePromptMiddleware` 亦须为零（类已迁走，`current_time_payload` 等仍在 time_context）。`app.agent.tool_result_storage`、`app.agent.prompt` 仍在原位，不清零；历史 `docs/`/`plan/` 记录不改。
4. LangGraph 平台入口：`langgraph.json` 指向的 `app/agent/build.py:make_graph` 可加载。
5. 循环导入：确认 `app.agent.build` → `app.tools` / `app.middleware`，反向无引用，无循环。
6. 落盘 middleware：新测试覆盖 `ToolMessage` / `Command` / 豁免工具 / async 四类路径，并验证 envelope 可被 `read_persisted_tool_result_slice` 读回（见 §3.4.B）。

## 5. 风险与回滚

- 提交①（graph/）风险低，纯路径迁移。
- 提交②（tools 三层）风险中：跨越约 12 个测试文件 + 三层互引 + 14 处 monkeypatch 字符串，是搬迁里最大的一块。必须原子完成、末尾全套 pytest 兜底；出错 `git revert` 整个提交②即可回到干净态。
- 提交③（middleware/）风险中：3.4.A 迁移为等价（低风险）；3.4.B 落盘中间件是**唯一的行为变更**，重点验证多态返回（`ToolMessage` / `Command`）处理正确、豁免生效、不与 xhs 旧逻辑双重落盘（xhs 手动落盘须同提交移除）。走 TDD。
- 分四次提交，边界清晰，便于精准回滚。

## 6. 后续可选（本次不做）

- 把工具专用提示 `ITINERARY_SYS` / `ACCOMMODATION_SYS` / `XHS_RESEARCH_SYS` 从 `agent/prompt.py` 下沉到 `tools/`，消除 `tools → agent.prompt` 残余依赖，使 `tools` 完全自洽。
- `state.py` 裸 `dict/list` 强类型化。
