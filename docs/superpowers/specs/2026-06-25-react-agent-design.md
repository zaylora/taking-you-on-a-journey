# ReAct 设计：全局单 Agent 自主决策架构

- 日期：2026-06-25
- 里程碑：ReAct（把固定编排图重构为全局单 Agent ReAct 循环）
- 范围：后端 `app/graph` 从「16 节点固定编排图」重构为「单一 ReAct Agent（LLM 推理循环）+ 一组确定性 tools」；保留 clarify 中断、summarize 流式、plan_patch 增量更新三项对前端的硬契约；前端按需小幅调整
- 验收标准：
  1. 用户的规划/修改/问答请求全部由**一个** ReAct Agent 处理，由 LLM 自主决定调用哪些工具、调用几次、何时收尾，不再有编译期写死的意图分流与节点路由。
  2. 费用核算（人均/整间口径）、超支判定、分天聚类、过夜日判定、`changed_days` 计算等**确定性业务规则**结果与重构前一致（回归测试保证）。
  3. 信息不足时 LLM **自主**调用 `ask_user` 提问并暂停，前端 `clarify` 弹窗交互不变；信息充分时 LLM 直接规划、不提问。
  4. 最终攻略仍由独立 `summarize` 节点逐 token 流式输出，前端打字机效果不变。
  5. plan 改动后前端地图仍能按 `changed_days` + `plan_version` 增量重绘。

## 决策摘要

| 决策点 | 选择 | 说明 |
|---|---|---|
| Agent 范式 | 全局单 Agent ReAct | 一个 LLM 推理循环替代 dispatch/clarify/retrieve/itinerary/refine/budget/answer 等节点的固定编排 |
| 循环实现 | `langchain.agents.create_agent` | langgraph 1.2.5 / langchain 1.3.9 下，`create_react_agent` 已弃用并迁移至此；围绕 middleware 体系，HITL/结构化输出可组合 |
| 业务规则归属 | 包成 tools，确定性纯函数保留 | LLM 决定「调哪个/几次/何时停」，但费用/聚类/过夜/diff 算法是 tool 内部纯函数，LLM 改不了 |
| 澄清提问 | `ask_user` 作为普通 tool，LLM 自主决定是否调用（决策点 B） | 取消固定 clarify 前置关卡；`interrupt()` 仅作「提问」动作的暂停机制 |
| changed_days | `finalize_plan` 内部新旧 day_plans 逐天 diff 自动计算（决策点 A） | 对 LLM 透明，前端增量重绘契约不变 |
| 最终攻略 | Agent 只产结构化 day_plans，收尾后独立 summarize 流式（决策点 C） | `stream.py` 的 `langgraph_node=="summarize"` token 放行逻辑零改动 |
| 前端 | 默认尽量少改，仅在 ReAct 收益明确处调整 | 用户已同意「可重构前端」，但本设计优先复用既有 SSE 事件契约 |
| 持久化 | 沿用既有 checkpointer（SQLite / MemorySaver） | thread_id + interrupt/resume 机制不变 |

## 1. 当前架构与问题

### 1.1 现状：确定性固定编排图

当前 `app/graph/builder.py` 是 16 个节点的静态图：

```
START → memory → dispatch_agent ─┬─ plan_new → reset → clarify ⟲ → retrieve
                                  │      (固定并行 fan-out 4 路检索)
                                  │      weather/attractions/restaurants/transport → itinerary
                                  │              ↓ (规则路由 route_after_*)
                                  │          accommodation / budget (超支回退→itinerary)
                                  ├─ refine → refine ──→ (按需重排)
                                  └─ qa    → answer
                                                        ↓
                                                    summarize → memory_update → END
```

关键特征（重构需逐一对齐）：

- **意图判断** `dispatch_agent`：规则优先（`_rule_based_intent` / `_infer_op`）+ LLM 兜底。
- **节点流转**：编译期写死的边 + `route_after_*` 规则路由函数（纯 if/else，不调 LLM）。
- **检索**：固定 4 路并行 fan-out，不按需选择。
- **工具调用**：各节点硬编码调用高德 API，LLM 不参与「决定调哪个工具」。

### 1.2 问题：缺乏自主决策灵活性

固定流程无法覆盖编排逻辑没预想到的请求，典型如：

- 「先帮我看看成都和重庆哪个更适合带娃，再规划」——需要先查两地再决策，固定流程做不到。
- 「这个行程第二天太赶，顺便帮我把预算也降到 3000」——一句话两个意图，规则 `_infer_op` 只能取一个。
- 「查一下景点，发现都太远了，那换个市中心的区域重规划」——需要「查→看结果→回头重规划」的循环，固定 DAG 无此回路。

ReAct 的价值正在于：LLM 在 Reason→Act→Observe 循环里**自主**应对这些组合。

### 1.3 必须保留的硬契约（重构的「暗礁」）

这些不是「流程死板」，是和前端/业务的硬约束，重构时**必须**对齐：

1. **clarify 的 `interrupt()` 暂停/resume**：前端靠 `EVENT_CLARIFY` 弹问题、`Command(resume=...)` 续跑（见 `stream.py:41,58-60`）。
2. **summarize 逐 token 流式**：`stream.py:49` 只放行 `metadata.langgraph_node=="summarize"` 的 token 做打字机效果。
3. **`EVENT_PLAN_PATCH` + `changed_days` + `plan_version`**：前端地图据此局部增量重绘（`stream.py:68-69`）。
4. **确定性业务规则**：费用人均/整间口径（`budget._sum_costs`）、超支回退（`compute_budget`，`_MAX_RETRY=2`）、分天聚类（`itinerary.cluster_by_day`）、过夜日（`accommodation.overnight_days`）。这些是 M4/M5 反复修过的，回归风险最高。

## 2. 目标架构

### 2.1 总览

```
START → context_prep (pre-hook: 装配 memory/会话上下文)
          ↓
   ┌────────────────────────────────────────────────────────┐
   │  trip_agent = create_agent(model, tools=[...], ...)       │
   │  ReAct 循环：Reason → 选 tool → Observe → 再 Reason → 收尾  │
   │                                                            │
   │  工具箱（LLM 自主调度）：                                    │
   │    检索类：search_attractions / search_restaurants /        │
   │            get_weather / plan_route                        │
   │    编排类：assemble_itinerary  (cluster_by_day + LLM 编排)   │
   │            assign_hotels       (overnight_days + attach)    │
   │    核算类：compute_budget       (M4 纯函数，返回超支建议)     │
   │    交互类：ask_user            (interrupt 暂停，HITL)        │
   │    收尾类：finalize_plan        (写 day_plans + diff 出       │
   │                                  changed_days + plan_version)│
   └────────────────────────────────────────────────────────┘
          ↓ (agent 结束循环)
   summarize (逐 token 流式，前端打字机契约不变)
          ↓
   memory_update → END
```

外层仍是一个极简的 LangGraph 图：`context_prep → trip_agent → summarize → memory_update`。`trip_agent` 是这张图里的一个**子图节点**（`create_agent` 返回的 compiled graph），承载全部决策。`summarize` / `memory_update` 沿用现有实现。

### 2.2 为什么外层还留一张图，而不是纯 agent

- **流式契约**：summarize 必须是独立节点，token 才能按 `langgraph_node=="summarize"` 被 `stream.py` 放行。若让 agent 自己写攻略，token 元数据是 agent 内部节点名，前端打字机会失效（C 决策）。
- **职责隔离**：agent 专注「规划决策 + 产结构化 day_plans」；攻略文案渲染是确定性收尾，不该占用 agent 的推理预算，也避免 agent 把长文案塞进 tool-calling 上下文。
- **中断点清晰**：`ask_user` 的 `interrupt()` 发生在 agent 子图内，外层 `stream.py` 流后探测 `snap.tasks[].interrupts` 的逻辑无需改动。

### 2.3 model / create_agent 落地形态

langgraph 1.2.5 + langchain 1.3.9 下：

```python
from langchain.agents import create_agent   # 1.x 推荐；create_react_agent 已弃用

trip_agent = create_agent(
    model=build_llm(temperature=0),          # 复用 app/llm/factory.build_llm
    tools=[search_attractions, search_restaurants, get_weather, plan_route,
           assemble_itinerary, assign_hotels, compute_budget,
           ask_user, finalize_plan],
    prompt=TRIP_AGENT_SYS,                    # 系统提示：赋予能力，不强制流程
    # checkpointer 由外层 build_graph 统一注入（见 §5）
)
```

> 实现第一步必须在真实环境验证 `create_agent` 的确切签名与 import（`langchain.agents` vs `langgraph.prebuilt`），并规避已知 bug：`langgraph-prebuilt==1.0.5` 传 `list[BaseTool]` 会崩，必要时锁 1.0.4。这是计划阶段的 Task 0。

## 3. 工具设计（确定性规则归属）

每个 tool = 「LLM 可调用的接口」+「内部确定性实现」。**LLM 决定调不调、调几次；tool 内部算法固定**。

### 3.1 检索类

| tool | 内部实现 | 复用 |
|---|---|---|
| `search_attractions(city, keywords)` | `amap.search_poi(city, kw, "风景名胜")` | 直接复用 `tools/amap.py`，失败降级空列表 |
| `search_restaurants(city, keywords)` | `amap.search_poi(city, kw, "餐饮")` | 同上 |
| `get_weather(city)` | `amap.get_weather(city)` | 同上，失败降级季节气候 |
| `plan_route(origin, dest, mode)` | `amap.plan_route(...)` | 同上 |

`amap.py` 已是干净 async 函数 + `@traceable`，几乎零改动包装成 `@tool`。

### 3.2 编排类（确定性聚类保留）

- `assemble_itinerary(...)`：内部先调 `itinerary.cluster_by_day`（**纯函数贪心聚类，原样保留**）做分天，再用现有 LLM 结构化输出（`DayPlans` schema）填充时间线。返回结构化 day_plans，不写 state。
- `assign_hotels(...)`：内部 `accommodation.overnight_days`（**过夜日纯函数保留**）判定过夜日 + `attach_hotels` 嵌入。

> LLM 自主决定：要不要调 `assemble_itinerary`（首次规划要、纯问答不要）、调用前是否已备齐 attractions/restaurants/weather（缺则先调检索）。

### 3.3 核算类（费用口径保留）

- `compute_budget(day_plans, num_people, limit)`：**直接复用 `budget.compute_budget` 纯函数**，人均/整间口径、`_MAX_RETRY` 不变。返回 `budget_check`（含 `over`/`estimated`/`breakdown`）与 `cut_suggestions`。
- **超支处理交给 LLM**：tool 只返回「超支了 + 削减建议」，是否重新 `assemble_itinerary` 压低成本由 LLM 在循环里自主决定（取代原 `route_after_budget` 的硬回退）。回归测试需验证「给定预算 limit + 超支场景，LLM 能收敛到不超支或给出 note」。

### 3.4 交互类（决策点 B：LLM 自主提问）

- `ask_user(field, question, options)`：内部调 `langgraph.types.interrupt({field, question, options})`，暂停图、抛出 payload 给前端（`EVENT_CLARIFY` 契约不变），resume 后 `interrupt()` 返回用户答案，作为 ToolMessage 回到 agent 循环。
- **决策权 100% 在 LLM**：系统提示告知「信息不足时可用 ask_user」，但调不调、问什么字段由 LLM 推理决定。取消现有 `clarify` 节点的固定 `_evaluate_gaps` 前置关卡和 `MAX_CLARIFY_ROUNDS` 强制轮次。
- 防呆：系统提示约束「同一字段不重复追问」「已知信息不再问」；可选地在 tool 内记录已问字段做软去重（不强制轮次上限，避免回到规则关卡）。

### 3.5 收尾类（决策点 A：自动 diff changed_days）

- `finalize_plan(day_plans)`：agent 完成规划/修改后调用，写入最终 `day_plans`。内部：
  1. 取 state 里旧 `day_plans` 与新 `day_plans` **逐天 diff**：比对每天的 items 指纹（name/type/poi_id 序列）+ hotel 指纹，算出 `changed_days`。
  2. `plan_version = old + 1`（仅当有 changed_days）。
  3. 写 `day_plans` / `changed_days` / `plan_version` 到 state。
- 纯问答场景 LLM 不调 `finalize_plan`，`changed_days` 为空，前端不重绘（对齐现有 `answer` 节点 `changed_days: []`）。
- diff 算法是新增的确定性纯函数 `diff_changed_days(old, new) -> list[int]`，需单测覆盖：整体新规划（全天 changed）、单天局部改（仅该天）、换酒店（过夜日 changed）、无改动（空）。

## 4. 状态与数据流

### 4.1 State

沿用 `TripState`（`graph/state.py`），ReAct 复用其字段。关键：

- `messages`（`add_messages`）：agent 循环的 tool-calling 消息历史天然落在这里。
- `day_plans` / `changed_days` / `plan_version` / `budget_check`：tool 写入，契约不变。
- 移除/弱化：`refine_request`、`clarified` / `clarify_round`、`last_intent` 等「固定编排专用」字段在 ReAct 下不再驱动路由（可保留为兼容字段，避免 checkpointer 老状态反序列化炸裂，但不再读）。

### 4.2 一次请求的数据流（首次规划，含自主澄清）

```
用户「帮我规划成都3天」
→ context_prep 装配上下文
→ trip_agent 循环：
    Reason: 城市/天数有了，缺日期但可默认 → 不问，直接查
    Act: get_weather("成都") → Observe 天气
    Act: search_attractions("成都","热门景点") → Observe POI
    Act: search_restaurants("成都","美食") → Observe
    Act: assemble_itinerary(...) → Observe 结构化 day_plans
    Act: assign_hotels(...) → Observe 嵌入酒店
    Act: compute_budget(...) → Observe 未超支
    Act: finalize_plan(day_plans) → 写 state + changed_days=[1,2,3]
    收尾（无更多 tool_call）
→ summarize 逐 token 流式攻略
→ memory_update → END
→ stream.py 发 EVENT_PLAN_PATCH(changed_days=[1,2,3]) + EVENT_FINAL
```

信息不足时（如未给城市）：agent 首步即 `Act: ask_user(field="city",...)` → `interrupt` 暂停 → `stream.py` 发 `EVENT_CLARIFY` → 用户答 → resume → 循环继续。

## 5. 外层图与 stream 桥接

### 5.1 build_graph 重构

```python
def build_graph(checkpointer=None):
    g = StateGraph(TripState)
    g.add_node("context_prep", context_prep)      # = 现 memory 节点（改名或沿用）
    g.add_node("trip_agent", trip_agent)          # create_agent 返回的子图
    g.add_node("summarize", summarize)            # 沿用
    g.add_node("memory_update", memory_update)    # 沿用
    g.add_edge(START, "context_prep")
    g.add_edge("context_prep", "trip_agent")
    g.add_edge("trip_agent", "summarize")
    g.add_edge("summarize", "memory_update")
    g.add_edge("memory_update", END)
    return g.compile(checkpointer=checkpointer or MemorySaver())
```

> `trip_agent` 作为子图节点嵌入时，checkpointer 由外层 compile 统一管理；需验证 1.2.5 下子图 interrupt 能正确冒泡到外层 `aget_state().tasks[].interrupts`（这是 `ask_user` 暂停能被 `stream.py` 探测的前提，列为计划阶段验证项）。

### 5.2 stream.py 改动评估

- `EVENT_CLARIFY` 探测（流后 `snap.tasks[].interrupts`）：**不变**，前提是子图 interrupt 正确冒泡（§5.1 验证项）。
- token 放行 `langgraph_node=="summarize"`：**不变**。
- `EVENT_NODE_START/END` 的 `NODES` / `NODE_LABELS`：需更新——节点集合从 16 个变为 `context_prep/trip_agent/summarize/memory_update`。agent 内部 tool 调用是否要发进度事件（如「正在检索景点」）是**可选增强**，非必须。
- `EVENT_PLAN_PATCH` / `EVENT_FINAL`：**不变**，仍读 `snap.values` 的 `day_plans/changed_days/plan_version/summary`。

### 5.3 前端改动评估

- 进度标签：现有前端按节点名显示进度（dispatch_agent/retrieve/...）。节点集合变了，进度标签需对应更新（小改）。若做了 §5.2 的 tool 进度事件增强，可显示更细的「检索景点/编排行程」。
- 其余（clarify 弹窗、打字机、地图增量重绘）：因契约不变，**零改动**。

## 6. 错误处理与降级

- 单个检索 tool 失败：内部已降级（空列表/季节气候），返回给 agent，LLM 据此决策（如换关键词重试或继续）。
- agent 循环不收敛 / 超 `recursion_limit`：`create_agent` 的 `remaining_steps` 机制会返回「需要更多步骤」的兜底 AIMessage，不抛 `GraphRecursionError`；需设置合理上限并在 summarize 给出友好提示。
- LLM 不调 `finalize_plan` 就结束：summarize 仍能基于 state 里既有 day_plans（可能为空）输出建议性文案，对齐现有「无 day_plans 走需求建议」分支（`summarize.py:13-16`）。
- 顶层异常：`stream.py` 现有 `except` 脱敏返回「生成失败，请重试」，**不变**。

## 7. 测试策略

### 7.1 确定性纯函数单测（回归保证，最高优先级）

- `diff_changed_days`：新增，覆盖全规划/单天改/换酒店/无改动。
- `compute_budget` / `cluster_by_day` / `overnight_days` / `attach_hotels`：复用现有单测，**结果必须与重构前逐字节一致**。

### 7.2 工具层单测

- 每个 tool 的 happy path + 降级路径（mock `amap.*`）。
- `ask_user` 的 interrupt payload 结构与 `EVENT_CLARIFY` 契约一致。

### 7.3 端到端（mock LLM tool_calls）

- 首次规划（不提问）：验证 tool 调用序列合理 + 产出 day_plans + changed_days 全天。
- 自主澄清：缺城市 → agent 首步 ask_user → interrupt → resume → 完成。
- 局部修改：「第二天太赶」→ agent 调 assemble/finalize → changed_days 仅含该天。
- 组合意图：「第二天太赶+预算降3000」→ agent 一轮内处理两件事。
- 超支收敛：给紧预算 → compute_budget 报超支 → agent 自主重排压低 → 不超支或给 note。

### 7.4 流式契约

- summarize token 逐字冒泡（沿用 M1 实测方式）。
- interrupt 暂停时流干净结束 + `EVENT_CLARIFY` 正确发出（沿用现有探针测试）。

## 8. 不做（YAGNI）

- 不引入多 Agent / supervisor（用户明确要全局**单** Agent）。
- 不重写前端交互范式（默认尽量少改；clarify/打字机/地图契约保留）。
- 不改持久化方案（沿用 checkpointer）。
- 不把攻略文案生成塞进 agent（保留独立 summarize）。
- 不引入 LangGraph middleware 的高级特性（PII/guardrails 等），除非验证 `create_agent` 的 HITL 必须经 middleware 才能 interrupt。

## 9. 迁移与风险

| 风险 | 缓解 |
|---|---|
| 子图 interrupt 不冒泡到外层 → ask_user 暂停失效 | 计划 Task 0 真实环境验证；若不冒泡，改用外层包一层 interrupt 转发或 middleware HITL |
| LLM 不调确定性 tool、自己瞎算费用/分天 → 业务回归 | 系统提示强约束「费用/分天/过夜必须调对应 tool」；端到端测试卡口 |
| `create_agent` 版本/bug（prebuilt 1.0.5） | Task 0 验证 + 必要时锁版本 |
| checkpointer 老状态字段不兼容 | 保留弃用字段为兼容占位，不删 TripState 键 |
| LLM 自主提问过多/死循环追问 | 系统提示「同一字段不重复问」+ 软去重；recursion_limit 兜底 |
| 重构期前后端进度标签错位 | §5.3 同步更新 NODES/标签；契约事件不动 |

## 10. 实现顺序（交 writing-plans 细化）

0. 真实环境验证 `create_agent` import/签名/子图 interrupt 冒泡/版本 bug。
1. 抽确定性纯函数为独立可测单元（`diff_changed_days` 新增；聚类/预算/过夜复用）。
2. 实现工具层（检索/编排/核算/ask_user/finalize_plan）+ 单测。
3. 组装 `trip_agent`（create_agent + 系统提示）。
4. 重构 `build_graph` 外层图 + `stream.py` 节点集合。
5. 端到端 + 流式契约测试。
6. 前端进度标签对齐。
