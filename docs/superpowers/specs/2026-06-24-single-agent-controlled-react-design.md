# 设计：单 Agent 受控 ReAct 收敛

- 日期：2026-06-24
- 范围：把当前多节点 / 多 Agent 编排收敛为一个 `trip_agent` 主节点；天气、景点、餐饮、交通、酒店、排行程、改行程、预算核算等能力降级为工具或工具内部函数。
- 验收标准：
  1. LangGraph 主拓扑收敛为 `START -> memory -> trip_agent -> memory_update -> END`。
  2. 新规划和修改行程统一走 `PlanChange -> apply_plan_change_tool`，不再拆成 `plan_trip()` / `refine_trip()` 两条业务链。
  3. 小范围修改按 `scope` 做最小变更，例如「第一天改成黄埔」只重查、重排第 1 天，并按需重算住宿 / 预算。
  4. `trip_agent` 是唯一对话 Agent；原天气、景点、餐饮、交通、住宿、预算等节点不再作为图节点接线。
  5. 后端测试不依赖真实 LLM / 高德网络；前端仍能通过 SSE 收到进度与最终回复。

## 1. 背景与问题

当前后端是 LangGraph 固定图编排：

```text
memory -> dispatch_agent -> clarify/retrieve/refine/answer
       -> weather/attractions/restaurants/transport
       -> itinerary/accommodation/budget/summarize -> memory_update
```

它不是标准 ReAct，而是「多节点工作流 + 若干 LLM 结构化输出 + 固定工具节点」。这个形态前期便于拆任务和展示进度，但现在复杂度已经超过收益：

- 图节点多，条件边多，理解一次用户修改要穿过多层路由。
- `TripState` 字段膨胀，大量字段只是节点间传递的中间态。
- 新规划、局部修改、问答被架构性分叉，导致相似能力散落在不同路径里。
- 天气 / 景点 / 餐饮 / 交通等节点多数只是固定 API 调用，不需要作为 Agent 存在。
- 修改行程本质也是生成一个新的 `day_plans`，和新规划应共享同一套变更模型与执行工具。

因此收敛目标不是「删除所有工具」，而是把智能决策集中到一个 Agent，把业务执行收进少量复合工具。

## 2. 决策摘要

| 决策点 | 选择 | 说明 |
|---|---|---|
| 主架构 | 单 `trip_agent` | 只保留一个对话 Agent，统一理解用户输入、决定是否调用工具、组织回复 |
| Agent 类型 | 受控 ReAct | Agent 可调用工具并观察结果，但只暴露少量复合工具，避免在十几个小工具间自由乱跳 |
| 业务模型 | `PlanChange` | 新规划、局部修改、预算调整、换酒店、纯问答都表示为同一类变更 / 非变更对象 |
| 工具粒度 | 复合工具优先 | 对 Agent 暴露 `apply_plan_change_tool` 等大工具；天气、POI、路线等小函数在工具内部调用 |
| 小范围修改 | 最小变更 | `scope` 由 Agent 解析，工具内部再按规则校验并推导实际影响范围 |
| LangGraph | 保留外壳 | 继续使用 checkpointer、SSE、memory / memory_update，降低迁移风险 |
| 前端进度 | 粗粒度 | 从多节点进度收敛为「理解需求 / 调整行程 / 生成回复」 |

## 3. 目标架构

目标拓扑：

```text
START
  -> memory
  -> trip_agent
  -> memory_update
  -> END
```

`trip_agent` 内部职责：

```text
trip_agent
  - 读取用户输入、当前计划、已知需求、会话摘要
  - 判断是否需要澄清
  - 解析 PlanChange
  - 选择并调用复合工具
  - 根据工具结果生成中文回复
```

`trip_agent` 不直接负责：

```text
- 手写 day_plans
- 编造坐标、路线、预算
- 直接实现 POI 检索、住宿选择、时间预算
- 维护多个图节点之间的中间状态
```

Agent 看到的是少量工具；工具内部可以继续调用已有高德封装、行程算法和预算逻辑。

## 4. PlanChange 统一变更模型

新规划和修改行程不再是两条架构路径，而是同一个变更模型的不同类型。

推荐 schema：

```python
from typing import Any, Literal

from pydantic import BaseModel, Field


class ChangeScope(BaseModel):
    kind: Literal["all", "plan", "days", "none"] = "plan"
    days: list[int] = Field(default_factory=list)


class PlanChange(BaseModel):
    type: Literal[
        "replace_plan",
        "update_day_region",
        "add_poi",
        "remove_poi",
        "replace_poi",
        "reorder_day",
        "set_pace",
        "set_budget",
        "set_hotel",
        "answer_only",
        "clarify",
    ]
    scope: ChangeScope = Field(default_factory=ChangeScope)
    requirements_patch: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    question: str = ""
    options: list[str] = Field(default_factory=list)
```

示例：

```json
{
  "type": "replace_plan",
  "scope": { "kind": "all", "days": [] },
  "requirements_patch": {
    "city": "广州",
    "days": 3,
    "budget": 3000
  },
  "constraints": {}
}
```

```json
{
  "type": "update_day_region",
  "scope": { "kind": "days", "days": [1] },
  "requirements_patch": {},
  "constraints": {
    "area": "黄埔"
  }
}
```

```json
{
  "type": "answer_only",
  "scope": { "kind": "none", "days": [] },
  "requirements_patch": {},
  "constraints": {},
  "question": "为什么第二天这么赶？"
}
```

## 5. 工具设计

### 5.1 暴露给 Agent 的复合工具

首版建议只暴露三个工具。

| 工具 | 职责 | 何时调用 |
|---|---|---|
| `apply_plan_change_tool` | 应用 `PlanChange`，返回新计划、变更说明、跳过原因 | 用户要新规划或修改计划 |
| `validate_plan_tool` | 检查现有计划的时间、预算、路线、住宿、字段完整性 | 用户问「合理吗」「预算够吗」，或生成后复核 |
| `answer_plan_question_tool` | 基于当前计划回答不改计划的问题 | `PlanChange.type == "answer_only"` |

`apply_plan_change_tool` 是主工具。它内部可以调用天气、景点、餐饮、交通、酒店、排程、预算等能力，但这些能力不必全部暴露给 Agent。

### 5.2 工具内部函数

现有模块可以归类为工具内部实现：

| 现有位置 | 新职责 |
|---|---|
| `app/tools/amap.py` | 原子工具：天气、POI、周边、路线、地理编码 |
| `app/itinerary/*` | 复合内部函数：POI 预过滤、时间窗、矩阵、优化、组装 |
| `app/graph/nodes/refine.py` | 迁移为 `apply_day_change` / `apply_plan_change` 的局部修改逻辑 |
| `app/graph/nodes/accommodation.py` | 迁移为 `recompute_accommodation` |
| `app/graph/nodes/budget.py` | 迁移为 `recompute_budget` |
| `app/graph/nodes/weather.py` 等检索节点 | 迁移为 `collect_travel_context` 内部调用 |

建议新增目录：

```text
backend/app/planning/
  __init__.py
  schemas.py          # PlanChange / TripPlanResult / Tool notes
  context.py          # collect_travel_context
  change.py           # apply_plan_change / apply_day_change
  validation.py       # validate_plan
  rendering.py        # 工具结果到回复素材的整理
```

## 6. apply_plan_change_tool 执行语义

输入：

```python
class ApplyPlanChangeInput(BaseModel):
    current_plan: dict = Field(default_factory=dict)
    requirements: dict = Field(default_factory=dict)
    change: PlanChange
```

输出：

```python
class TripPlanResult(BaseModel):
    status: Literal["applied", "partial", "needs_clarification", "failed", "answered"]
    requirements: dict = Field(default_factory=dict)
    day_plans: list[dict] = Field(default_factory=list)
    budget_check: dict = Field(default_factory=dict)
    changed_days: list[int] = Field(default_factory=list)
    applied: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    question: str = ""
    options: list[str] = Field(default_factory=list)
```

执行规则：

1. 合并 `requirements_patch` 到当前 requirements。
2. 根据 `change.type` 和 `scope` 推导实际影响范围。
3. 按影响范围补充外部数据。
4. 生成或更新 `day_plans`。
5. 按需重算交通、住宿、预算。
6. 返回结构化结果，不直接写自然语言长文。

## 7. 最小变更规则

| PlanChange | 影响范围 | 执行策略 |
|---|---|---|
| `replace_plan` | 全量 | 重新查上下文、重新生成全部 `day_plans`、重算住宿和预算 |
| `update_day_region` | 指定天 | 只 geocode 新区域，围绕新区域查景点 / 餐饮，只重排目标天，住宿 / 预算按需重算 |
| `add_poi` | 指定天 | 围绕目标天 center 查 POI，插入后重算当天交通和预算 |
| `remove_poi` | 指定天 | 删除目标项，重算当天交通和预算 |
| `replace_poi` | 指定天 | 定位旧项，查新候选，替换后重算当天交通和预算 |
| `reorder_day` | 指定天 | 只重排目标天，不查新 POI，通常不重算住宿 |
| `set_pace` | 指定天或全局 | 对影响天删减 / 补充项目，再重算交通和预算 |
| `set_budget` | 计划级 | 先只重算预算；超支时再按规则局部调整 |
| `set_hotel` | 住宿级 | 只重算住宿，`day_plans` 不动 |
| `answer_only` | 无 | 不改计划，调用问答工具 |

工具内部不能完全相信 Agent 给出的 `scope`。例如 `type == "update_day_region"` 但 `scope.kind == "all"` 时，工具应以 `constraints.day` 或 `scope.days` 推导目标天；无法定位则返回 `needs_clarification`，不能全量重做。

## 8. trip_agent 行为

`trip_agent` 是受控 ReAct Agent。它可以根据状态调用工具，但遵守以下边界：

- 必须先输出或内部形成结构化 `PlanChange`。
- 计划变更一律通过 `apply_plan_change_tool`，不能直接改 `day_plans`。
- 纯问答优先用 `answer_plan_question_tool`。
- 工具返回 `needs_clarification` 时，直接把问题交给用户。
- 工具返回 `partial` 时，回复里必须说明哪些已完成、哪些跳过。

推荐 `TripAgentDecision`：

```python
class TripAgentDecision(BaseModel):
    change: PlanChange
    rationale: str = ""
```

`rationale` 只用于调试和日志，不展示给用户。

## 9. LangGraph 与 SSE 影响

### 9.1 图构建

`backend/app/graph/builder.py` 收敛为：

```text
START -> memory -> trip_agent -> memory_update -> END
```

旧节点文件首版不删除，只是不接线。这样便于回滚和迁移测试。

### 9.2 进度事件

后端 SSE 事件从多节点进度收敛为粗粒度阶段：

```text
understand_request  理解需求
apply_plan_change   调整行程
render_response     生成回复
```

前端 `AgentProgress.vue` 只需要展示这三类兜底标签。原节点名标签可以暂时保留兼容，但新链路只发新阶段。

## 10. 状态收敛

首版为了降低风险，`TripState` 不立刻大删字段，只新增 / 复用必要字段：

```text
last_intent
normalized_req
day_plans
budget_check
changed_days
refine_notes
summary
```

新字段建议：

```text
plan_change
tool_result
pending_clarification
```

第二阶段再把 `weather / attractions / restaurants / transport` 等中间字段从主 state 中移走，改为工具内部临时变量或 `tool_result` 的局部内容。

## 11. 迁移计划

### 阶段 1：协议与工具层

目标：先建立 `PlanChange` 和复合工具，不改图拓扑。

- 新增 `backend/app/planning/schemas.py`。
- 新增 `backend/app/planning/change.py`，先包装现有 refine / itinerary / accommodation / budget 能力。
- 新增工具单测，覆盖 `replace_plan`、`update_day_region`、`set_budget`、`answer_only`。

验证：

```text
cd backend
uv run pytest tests/test_plan_change*.py tests/test_planning*.py
```

### 阶段 2：新增 trip_agent

目标：新增主 Agent，但先不删除旧节点。

- 新增 `backend/app/graph/nodes/trip_agent.py`。
- 用 structured output 解析 `TripAgentDecision`。
- 将 `apply_plan_change_tool`、`validate_plan_tool`、`answer_plan_question_tool` 绑定给 Agent。
- 单测覆盖新规划、局部修改、问答、澄清。

验证：

```text
cd backend
uv run pytest tests/test_trip_agent.py
```

### 阶段 3：切换图拓扑

目标：把主图切到单 Agent。

- 修改 `backend/app/graph/builder.py`。
- 修改 `backend/tests/test_dispatch_topology.py` 或新增 `test_single_agent_topology.py`。
- 更新前端进度标签。

验证：

```text
cd backend
uv run pytest tests/test_single_agent_topology.py tests/test_chat_stream.py
```

### 阶段 4：迁移旧测试

目标：把旧节点测试迁移为工具测试与 Agent 流程测试。

- `test_refine_*` 迁移到 `planning/change.py`。
- `test_parallel_retrieval.py` 迁移到 `planning/context.py`。
- `test_multiturn_*` 改为走 `trip_agent`。
- 保留已有高德 / LLM 打桩策略。

验证：

```text
cd backend
uv run pytest
```

### 阶段 5：清理旧节点

目标：新链路稳定后再删除不接线节点。

- 删除或归档 `weather.py`、`attractions.py`、`restaurants.py`、`transport.py`、`retrieve.py` 等纯图节点。
- `dispatch_agent.py`、`clarify.py`、`refine.py`、`answer.py` 的可复用逻辑迁移后再删。
- `rg` 确认无引用。

验证：

```text
rg -n "dispatch_agent|retrieve|route_after_dispatch|route_after_clarify" backend/app backend/tests
cd backend
uv run pytest
```

## 12. 测试策略

测试按三层组织：

1. Schema 测试：验证 `PlanChange` 的必填字段、scope、序列化形状。
2. 工具测试：验证 `apply_plan_change_tool` 的最小变更规则，不依赖真实网络。
3. Agent / 图测试：验证 `trip_agent` 的决策、工具调用、SSE 输出和 memory 更新。

关键用例：

- 新规划广州 3 天：全量生成计划。
- 第一天改成黄埔：只改第 1 天，其他天不变。
- 预算改成 3000：先重算预算，不无条件重排。
- 第二天加博物馆：只重排第 2 天。
- 用户问「为什么第二天这么赶」：不改计划。
- 信息不足：返回澄清问题，而不是编造计划。
- 工具部分失败：返回 `partial` 和 `skipped`，回复诚实说明。

## 13. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 单 Agent 变成大黑箱 | 强制结构化 `PlanChange`；计划变更只能通过复合工具 |
| 复合工具过大 | 按 `schemas/context/change/validation` 拆文件；工具内部函数单测覆盖 |
| Agent 漏调用校验 | `apply_plan_change_tool` 内部自带必要校验；`validate_plan_tool` 用于显式问答和后续增强 |
| 小范围修改被误判成全量 | 工具内部按 `change.type` 二次推导影响范围，不盲信 Agent scope |
| 前端进度变少 | 明确收敛为三阶段，牺牲细粒度观测换简单性 |
| 旧测试大量失效 | 分阶段迁移，旧节点先保留不删，图切换后再清理 |

## 14. 非目标

首版不做：

- 不彻底删除 LangGraph。
- 不把所有原子函数都暴露给 LLM 自由调用。
- 不让 LLM 直接生成完整 `day_plans` 替代确定性排程。
- 不一次性重写前端 UI。
- 不做跨城市、多目的地复杂联程。
- 不做完整酒店真实预订链路。

## 15. 推荐实施顺序

最稳顺序是：

```text
PlanChange schema
  -> apply_plan_change_tool
  -> trip_agent
  -> 单 Agent 图拓扑
  -> 测试迁移
  -> 旧节点清理
```

每一步都应能独立测试和提交。不要在同一个改动里同时重写 schema、切图、删旧节点和改前端。
