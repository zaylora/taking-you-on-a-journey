# ReAct 设计：全局单 Agent 自主决策架构

- 日期：2026-06-25
- 里程碑：ReAct（把固定编排图重构为全局单 Agent ReAct 循环）
- 范围：后端 `app/graph` 从「16 节点固定编排图」重构为**一个** ReAct Agent（`create_agent`）+ 一组确定性 tools。外层不再有任何包裹节点（`memory` / `context_prep` / `summarize` / `memory_update` 全部去掉）；`build_graph` 直接返回 `create_agent(...)` 作为 `app.state.graph`。保留 clarify 中断、最终回复流式、plan_patch 增量更新三项对前端的硬契约；前端按需小幅调整。
- 验收标准：
  1. 用户的规划/修改/问答请求全部由**一个** ReAct Agent 处理，由 LLM 自主决定调用哪些工具、调用几次、何时收尾，不再有编译期写死的意图分流、节点路由与外围包裹节点。
  2. 费用核算（人均/整间口径）、超支判定、分天聚类、过夜日判定、`changed_days` 计算等**确定性业务规则**结果与重构前一致（回归测试保证）。
  3. 信息不足时 LLM **自主**调用 `ask_user` 提问并暂停，前端 `clarify` 弹窗交互不变；信息充分时 LLM 直接规划、不提问。
  4. 最终回复（规划攻略 / QA 答案）由 **agent 本体**逐 token 流式输出，前端打字机效果不变；agent 中间自然语言文本（思考/说明）也一并流出（用户接受可见），仅工具原始 JSON 不流。
  5. plan 改动后前端地图仍能按 `changed_days` + `plan_version` 增量重绘。

## 决策摘要

| 决策点 | 选择 | 说明 |
|---|---|---|
| Agent 范式 | 全局单 Agent ReAct，外层无包裹节点 | `build_graph` 直接返回 `create_agent(...)`；上下文历史与 interrupt/resume 全走 checkpointer |
| 循环实现 | `langchain.agents.create_agent` | langgraph 1.2.5 / langchain 1.3.9 下 `create_react_agent` 已弃用并迁移至此 |
| 业务规则归属 | 包成 tools，确定性纯函数保留 | LLM 决定「调哪个/几次/何时停」，但费用/聚类/过夜/diff 算法是 tool 内纯函数，LLM 改不了 |
| 澄清提问 | `ask_user` 作为普通 tool，LLM 自主决定是否调用（决策 B） | 取消固定 clarify 前置关卡；`interrupt()` 仅作「提问」动作的暂停机制 |
| changed_days | `finalize_plan` 内部新旧 day_plans 逐天 diff 自动计算（决策 A） | 对 LLM 透明，前端增量重绘契约不变 |
| 最终回复 | agent 本体输出（规划攻略 / QA 答案统一），中间文本可见（决策 C） | 不引入收尾节点；流式放行 model 文本 token、不流工具原始 JSON（§2.3），规则极简无需实测过滤 |
| 上下文 / 消息历史 | 全靠 `create_agent` + checkpointer 的 `messages` | 取代原 `memory`（装配上下文）与 `memory_update`（追加消息）两个节点，二者删除 |
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
- **外围节点**：`memory`（装配上下文）/ `summarize`（写攻略流式）/ `memory_update`（追加消息）—— ReAct 下全部冗余。

### 1.2 问题：缺乏自主决策灵活性

固定流程无法覆盖编排逻辑没预想到的请求，典型如：

- 「先帮我看看成都和重庆哪个更适合带娃，再规划」——需要先查两地再决策，固定流程做不到。
- 「这个行程第二天太赶，顺便帮我把预算也降到 3000」——一句话两个意图，规则 `_infer_op` 只能取一个。
- 「查一下景点，发现都太远了，那换个市中心的区域重规划」——需要「查→看结果→回头重规划」的循环，固定 DAG 无此回路。

ReAct 的价值正在于：LLM 在 Reason→Act→Observe 循环里**自主**应对这些组合。

### 1.3 必须保留的硬契约（重构的「暗礁」）

这些不是「流程死板」，是和前端/业务的硬约束，重构时**必须**对齐：

1. **clarify 的 `interrupt()` 暂停/resume**：前端靠 `EVENT_CLARIFY` 弹问题、`Command(resume=...)` 续跑（见 `stream.py:41,58-60`）。
2. **最终回复逐 token 流式**：`stream.py:49` 现按 `metadata.langgraph_node=="summarize"` 放行 token 做打字机效果。重构后由 agent 本体输出，改为放行所有 `on_chat_model_stream` 文本 token（中间文本+最终回复，§2.3），工具原始 JSON 不走该事件、天然不流。
3. **`EVENT_PLAN_PATCH` + `changed_days` + `plan_version`**：前端地图据此局部增量重绘（`stream.py:68-69`）。
4. **确定性业务规则**：费用人均/整间口径（`budget._sum_costs`）、超支回退（`compute_budget`，`_MAX_RETRY=2`）、分天聚类（`itinerary.cluster_by_day`）、过夜日（`accommodation.overnight_days`）。这些是 M4/M5 反复修过的，回归风险最高。
5. **API 契约**：`main.py:50` 用 `build_graph(checkpointer=...)` 得到 `app.state.graph`；`stream.py` 用 `graph.astream_events` / `aget_state`。`build_graph` 重构后**签名不变**（仍收 checkpointer、仍返回 compiled graph），`main.py` 零改动。

## 2. 目标架构

### 2.1 总览

```
app.state.graph = build_graph(checkpointer)   # 直接 = create_agent(...)

START → trip_agent (create_agent ReAct 循环) → END

   trip_agent = create_agent(model, tools=[...], prompt=TRIP_AGENT_SYS, checkpointer=...)
   ReAct 循环：Reason → 选 tool → Observe → 再 Reason → 收尾轮（无 tool_call，本体输出最终回复）

   工具箱（LLM 自主调度）：
     检索类：search_attractions / search_restaurants / get_weather / plan_route
     编排类：assemble_itinerary  (cluster_by_day 纯函数 + LLM 编排)
             assign_hotels       (overnight_days 纯函数 + attach_hotels)
     核算类：compute_budget       (M4 纯函数，返回超支建议)
     交互类：ask_user            (interrupt 暂停，HITL；LLM 自主决定是否调用)
     收尾类：finalize_plan        (写 day_plans + 自动 diff 出 changed_days/plan_version)
     最终回复：agent 本体在最后一轮（无 tool_call）直接流式输出
               —— 规划场景写攻略、QA 场景答问题，均由 agent 输出
```

**没有外层包裹节点**。`build_graph(checkpointer)` 直接返回 `create_agent(...)` 的 compiled graph。

- **上下文 / 历史**：`create_agent` 通过 checkpointer 自动维护 `messages`（含历次 user/AI/tool 消息）。取代原 `memory` 节点的上下文装配。
- **本轮消息落库**：agent 循环天然把本轮 user 消息与最终 AIMessage 写入 `messages`（`add_messages`）。取代原 `memory_update` 节点的手动追加。
- **`summary` 字段**：`EVENT_FINAL` 需要的最终回复文本，由 `stream.py` 从 agent 末条 AIMessage 取（`snap.values["messages"][-1].content`），不再由独立节点写。

### 2.2 上下文与会话延续

- 多轮：同一 `thread_id` 下，checkpointer 恢复 `messages`，agent 自然看到「刚才那个行程」「第二天」等指代——无需 `memory` 节点装配 `memory_context`。
- 当前行程：`day_plans` 等仍在 state，agent 可在 prompt/tool 读到；修改类请求基于既有 `day_plans` 增量改（见 §3.5）。
- resume：`ask_user` 的 `interrupt()` 暂停后，`Command(resume=...)` 续跑，checkpointer 保证状态连续（机制同现状）。

### 2.3 最终回复的输出与流式（决策 C：agent 本体输出，中间文本可见）

最终回复（规划攻略 / QA 答案）由 **agent 本体**输出，规划与 QA 统一，不引入收尾节点。

**用户决策：agent 的中间自然语言文本（思考、说明，如「我先查一下天气…」）可以冒出来给用户看。** 这消除了「区分中间文本 vs 最终回复」的难题——既然两者都放行，就不需要按 tag / `disable_streaming` 精密分离，也无需 Task 0 实测过滤准确率。

**流式过滤规则极简**：放行 **model 节点**产出的文本 token（中间思考 + 最终攻略/答案都流），**挡掉 tools 节点**的原始输出（高德 POI 的大段 JSON、tool_call 函数名+参数）——否则聊天框会出现乱码/代码。判定即：

```
on_chat_model_stream 且 metadata.langgraph_node != "tools" → 放行该 token
```

（`create_agent` 中产出文本的是 model 节点，tools 节点只产 ToolMessage，本就不发 `on_chat_model_stream`；该判定主要是兜底/语义明确。实际只需放行 `on_chat_model_stream` 的文本 token 即可，工具的原始 JSON 不走该事件。）

- **`disable_streaming`**：`build_llm` 当前默认 `"tool_calling"`（factory.py:14），会抑制 tool-calling 轮的流式。本方案需中间文本也流出，故 agent 的 model **改为正常流式**（构造时传 `disable_streaming=False` 或等价）。Task 0 确认该 override 不影响 tool-calling 正确性。
- **职责自适应**：agent 改了行程（调过 `finalize_plan`）就在收尾文本里写逐日攻略；纯 QA（未改行程）就直接答问题，不套攻略模板。

> 子图事件冒泡：`create_agent` 即 compiled graph，其内部 model 节点的 `on_chat_model_stream` 事件正常出现在 `astream_events` 流中。`summary`（`EVENT_FINAL` 用）从 agent 末条 AIMessage 取。

### 2.4 create_agent 落地形态

langgraph 1.2.5 + langchain 1.3.9 下：

```python
from langchain.agents import create_agent   # 1.x 推荐；create_react_agent 已弃用

def build_graph(checkpointer=None):
    return create_agent(
        model=build_llm(temperature=0, disable_streaming=False),  # 关流式抑制，中间文本也流
        tools=[search_attractions, search_restaurants, get_weather, plan_route,
               assemble_itinerary, assign_hotels, compute_budget,
               ask_user, finalize_plan],
        system_prompt=TRIP_AGENT_SYS,          # 注意：参数名是 system_prompt（非 prompt）
        state_schema=TripState,                # 继承 AgentState，加 day_plans 等业务字段
        checkpointer=checkpointer or MemorySaver(),
    )
```

> **Task 0 已在真实环境（uv run，langchain 1.x / langgraph 1.2.5）验证通过**：
> - `from langchain.agents import create_agent` 可用；参数含 `model/tools/system_prompt/state_schema/checkpointer/interrupt_before/interrupt_after/response_format/middleware` 等。
> - 自定义 state：`from langchain.agents import AgentState`，`class TripState(AgentState): day_plans: list ...`，编译通过。
> - tool 读写 state：`InjectedState`（读，`from langgraph.prebuilt import InjectedState`）、`Command(update={...})`（写，`from langgraph.types import Command`）、`InjectedToolCallId`（`from langchain_core.tools import InjectedToolCallId`，写 ToolMessage 用）。
> - `ask_user` 的 `interrupt()`（`from langgraph.types import interrupt`）**冒泡到 `aget_state().tasks[].interrupts`**，`stream.py` 现有 `EVENT_CLARIFY` 探测逻辑可直接复用；`Command(resume=...)` 续跑正常；`messages` 自动累积；末条 AIMessage.content 即最终回复。
> - 仍需实现时注意：`create_agent` 会对 model 调 `bind_tools`（真实模型支持，FakeChatModel 不支持）；规避 `langgraph-prebuilt==1.0.5` 传 `list[BaseTool]` 的已知 bug（必要时锁 1.0.4，当前装的版本 Task 0 编译未触发）。

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

- `assemble_itinerary(...)`：内部先调 `cluster_by_day`（**纯函数贪心聚类，原样保留**）做分天，再用现有 LLM 结构化输出（`DayPlans` schema）填充时间线。返回结构化 day_plans。
- `assign_hotels(...)`：内部 `overnight_days`（**过夜日纯函数保留**）判定过夜日 + `attach_hotels` 嵌入。

> LLM 自主决定：要不要调 `assemble_itinerary`（首次规划要、纯问答不要）、调用前是否已备齐 attractions/restaurants/weather（缺则先调检索）。

### 3.3 核算类（费用口径保留）

- `compute_budget(day_plans, num_people, limit)`：**直接复用 `compute_budget` 纯函数**，人均/整间口径、`_MAX_RETRY` 不变。返回 `budget_check`（含 `over`/`estimated`/`breakdown`）与 `cut_suggestions`。
- **超支处理交给 LLM**：tool 只返回「超支了 + 削减建议」，是否重新 `assemble_itinerary` 压低成本由 LLM 自主决定（取代原 `route_after_budget` 硬回退）。端到端测试验证「给定预算 + 超支场景，LLM 能收敛到不超支或给出 note」。

### 3.4 交互类（决策 B：LLM 自主提问）

- `ask_user(field, question, options)`：内部调 `langgraph.types.interrupt({field, question, options})`，暂停图、抛 payload 给前端（`EVENT_CLARIFY` 契约不变），resume 后 `interrupt()` 返回用户答案，作为 ToolMessage 回到 agent 循环。
- **决策权 100% 在 LLM**：系统提示告知「信息不足时可用 ask_user」，但调不调、问什么字段由 LLM 推理决定。取消现有 `clarify` 的固定 `_evaluate_gaps` 关卡和 `MAX_CLARIFY_ROUNDS` 强制轮次。
- 防呆：系统提示约束「同一字段不重复追问」「已知信息不再问」；可选地在 tool 内记录已问字段做软去重（不强制轮次上限）。

### 3.5 收尾类（决策 A：自动 diff changed_days）

- `finalize_plan(day_plans)`：agent 完成规划/修改后调用，写入最终 `day_plans`。内部：
  1. 取 state 旧 `day_plans` 与新 `day_plans` **逐天 diff**：比对每天 items 指纹（name/type/poi_id 序列）+ hotel 指纹，算出 `changed_days`。
  2. `plan_version = old + 1`（仅当有 changed_days）。
  3. 写 `day_plans` / `changed_days` / `plan_version` 到 state。
- 纯问答场景 LLM 不调 `finalize_plan`，`changed_days` 为空，前端不重绘。
- diff 算法是新增确定性纯函数 `diff_changed_days(old, new) -> list[int]`，单测覆盖：整体新规划（全天）、单天局部改（仅该天）、换酒店（过夜日）、无改动（空）。

## 4. 状态与数据流

### 4.1 State

`create_agent` 默认 state 仅 `messages`。本项目业务字段（`day_plans`/`changed_days`/`plan_version`/`budget_check`）需挂在 state 上供 tool 读写、供 `stream.py` 读出——Task 0 确认 `create_agent` 接受自定义 `state_schema`（或等价机制）。

- 保留字段：`messages`、`day_plans`、`changed_days`、`plan_version`、`budget_check`、`summary`（可选，若不从末条 AIMessage 取则保留）。
- **直接删除**（代码简洁要求，不留兼容占位）：`refine_request`、`clarified` / `clarify_round`、`last_intent`、`normalized_req`、`budget_advice`、`retry_count`、`daily_centers`、`conversation_summary`、`memory_context` 等「固定编排专用」字段。Task 0 实测老 checkpointer 会话反序列化：`TypedDict` 多余键通常忽略；炸则加载清洗或丢弃测试期老会话。删字段前全仓 grep 确认无残余读点。

### 4.2 一次请求的数据流（首次规划，含自主澄清）

```
用户「帮我规划成都3天」（thread_id 经 checkpointer 恢复 messages）
→ trip_agent 循环：
    Reason: 城市/天数有了，缺日期可默认 → 不问，直接查
    Act: get_weather("成都") → Observe
    Act: search_attractions("成都","热门景点") → Observe
    Act: search_restaurants("成都","美食") → Observe
    Act: assemble_itinerary(...) → Observe 结构化 day_plans
    Act: assign_hotels(...) → Observe 嵌入酒店
    Act: compute_budget(...) → Observe 未超支
    Act: finalize_plan(day_plans) → 写 state + changed_days=[1,2,3]
    收尾轮（无 tool_call）：agent 本体流式输出逐日攻略
→ END
→ stream.py：放行最终回复 token（§2.3）；末条 AIMessage → summary；
  发 EVENT_PLAN_PATCH(changed_days=[1,2,3]) + EVENT_FINAL
```

信息不足时（如未给城市）：agent 首步 `ask_user(field="city",...)` → `interrupt` 暂停 → `EVENT_CLARIFY` → 用户答 → resume → 续跑。

## 5. stream 桥接与前端

### 5.1 build_graph

`build_graph(checkpointer)` 直接返回 `create_agent(...)`（§2.4），不再构造 `StateGraph`、不再有 `add_node/add_edge`。`main.py:50` 调用零改动。

> Task 0 验证：`create_agent` 返回的 graph 支持 `astream_events(version="v2")` 与 `aget_state()`（`stream.py` 依赖），interrupt 暂停后 `aget_state().tasks[].interrupts` 可取澄清 payload。

### 5.2 stream.py 改动

- `EVENT_CLARIFY` 探测（流后 `snap.tasks[].interrupts`）：**逻辑不变**，确认 `create_agent` 的 interrupt 出现在 `aget_state().tasks`（Task 0）。
- token 放行（**主要改动**）：从「`langgraph_node=="summarize"`」改为「放行所有 `on_chat_model_stream` 文本 token」（§2.3：中间思考 + 最终回复都流，工具原始 JSON 不走该事件天然不流）。同时 agent 的 model 关闭 `disable_streaming`（改正常流式）以让中间文本也能流出。
- `summary`：从 `snap.values["messages"][-1].content` 取最终回复文本，供 `EVENT_FINAL`。
- `EVENT_NODE_START/END` 的 `NODES` / `NODE_LABELS`：节点集合大幅缩减（仅 agent 内部 `model`/`tools` 节点）。进度展示策略改为「按 tool 调用名报进度」（可选增强）或简化为「思考中/生成中」。
- `EVENT_PLAN_PATCH` / `EVENT_FINAL`：**不变**，仍读 `snap.values` 的 `day_plans/changed_days/plan_version` + 上面取的 `summary`。

### 5.3 前端改动

- 进度标签：节点集合变了，进度展示需调整（小改；或改为基于 tool 名/通用文案）。
- clarify 弹窗、打字机、地图增量重绘：因契约（`EVENT_CLARIFY`/`EVENT_TOKEN`/`EVENT_PLAN_PATCH`/`EVENT_FINAL`）保留，**基本零改动**。

## 6. 错误处理与降级

- 单个检索 tool 失败：内部已降级（空列表/季节气候），返回给 agent，LLM 据此决策。
- agent 循环不收敛 / 超 `recursion_limit`：`create_agent` 的 `remaining_steps` 返回兜底 AIMessage（不抛 `GraphRecursionError`），该兜底文本即作为最终回复透出。
- LLM 不调 `finalize_plan` 就结束（纯 QA / 信息不足）：agent 本体最终回复仍能基于 messages 与已有 day_plans 给出回答或建议。
- 顶层异常：`stream.py` 现有 `except` 脱敏返回「生成失败，请重试」，**不变**。
- 系统提示需引导：收尾轮必须产出面向用户的最终回复，避免空回复。

## 7. 测试策略

### 7.1 确定性纯函数单测（回归保证，最高优先级）

- `diff_changed_days`：新增，覆盖全规划/单天改/换酒店/无改动。
- `compute_budget` / `cluster_by_day` / `overnight_days` / `attach_hotels`：复用现有单测，**结果与重构前逐字节一致**。

### 7.2 工具层单测

- 每个 tool 的 happy path + 降级路径（mock `amap.*`）。
- `ask_user` 的 interrupt payload 结构与 `EVENT_CLARIFY` 契约一致。

### 7.3 端到端（mock LLM tool_calls）

- 首次规划（不提问）：tool 调用序列合理 + 产出 day_plans + changed_days 全天。
- 自主澄清：缺城市 → ask_user → interrupt → resume → 完成。
- 局部修改：「第二天太赶」→ assemble/finalize → changed_days 仅该天。
- 组合意图：「第二天太赶+预算降3000」→ 一轮内处理两件事。
- 超支收敛：紧预算 → compute_budget 报超支 → agent 自主重排 → 不超支或给 note。
- 纯 QA：「那个餐厅离地铁远吗」→ 不调 finalize_plan → agent 本体答问题 → changed_days 空。

### 7.4 流式契约

- 文本 token 逐字冒泡（中间思考 + 最终回复都流），工具原始 JSON **不**出现在 token 流里。
- interrupt 暂停时流干净结束 + `EVENT_CLARIFY` 正确发出（沿用现有探针测试）。

## 8. 不做（YAGNI）

- 不引入多 Agent / supervisor（用户明确要全局**单** Agent）。
- 不保留任何外围包裹节点（`memory`/`context_prep`/`summarize`/`memory_update` 全删）。
- 不重写前端交互范式（默认尽量少改；clarify/打字机/地图契约保留）。
- 不改持久化方案（沿用 checkpointer）。
- 不引入 LangGraph middleware 高级特性（PII/guardrails 等），除非 Task 0 证明 HITL/流式过滤必须经 middleware。

> 死代码删除（§11）是本次范围内的收尾工作，不是 YAGNI 排除项——用户明确要求重构后保证代码简洁、不留兼容占位。

## 9. 迁移与风险

| 风险 | 缓解 |
|---|---|
| `create_agent` interrupt 不在 `aget_state().tasks` → ask_user/clarify 失效 | Task 0 真实环境验证；不行则用 middleware HITL 或自定义中断转发 |
| `create_agent` 默认 state 仅 messages，业务字段无处放 | Task 0 确认自定义 `state_schema` / `InjectedState` / `Command` 机制 |
| 工具原始 JSON 误流到聊天框 | 只放行 `on_chat_model_stream` 文本 token，工具 ToolMessage 不走该事件（§2.3）；端到端校验 |
| LLM 不调确定性 tool、自己瞎算费用/分天 → 业务回归 | 系统提示强约束「费用/分天/过夜必须调对应 tool」；端到端测试卡口 |
| `create_agent` 版本/bug（prebuilt 1.0.5） | Task 0 验证 + 必要时锁版本 |
| checkpointer 老状态字段不兼容（已直接删字段） | Task 0 实测反序列化；TypedDict 多余键通常忽略；炸则清洗或丢弃测试期老会话 |
| LLM 自主提问过多/死循环追问 | 系统提示「同一字段不重复问」+ 软去重；recursion_limit 兜底 |

## 10. 实现顺序（交 writing-plans 细化）

0. **Task 0 真实环境验证**：`create_agent` import/签名/checkpointer/interrupt 冒泡/自定义 state_schema/版本 bug/老会话反序列化；确认关闭 `disable_streaming` 后 tool-calling 仍正确、`on_chat_model_stream` 文本 token 正常冒泡且工具 JSON 不混入。任一关键项不通过 → 回报用户调整 spec。
1. 抽确定性纯函数为独立可测单元（迁入 `tools/` 或 `core/`；`diff_changed_days` 新增；聚类/预算/过夜复用）。
2. 实现工具层（检索/编排/核算/ask_user/finalize_plan）+ 单测。
3. 组装 `build_graph` = `create_agent`（系统提示 + tools + state_schema + checkpointer）。
4. 改 `stream.py`（token 过滤 + summary 取末条 AIMessage + 节点/进度）+ `constants.py`（NODES/标签清理、删 `MAX_CLARIFY_ROUNDS`、评估删 `EVENT_INTENT`）。
5. 端到端 + 流式契约测试。
6. 前端进度标签对齐。
7. **死代码清理**（§11）：删除清单中所有文件，全仓 grep 确认无残余 import/读点，跑全量测试绿。

## 11. 死代码删除清单（代码简洁要求）

重构后下列不再使用，确定性纯函数迁出后**整文件删除**，不留兼容占位。删除前对每个符号全仓 `grep` 确认无残余引用，删除后跑全量测试。

### 11.1 整文件删除

| 文件 | 处理 | 去向 |
|---|---|---|
| `graph/nodes/dispatch_agent.py` | 删 | 意图分流由 ReAct 循环取代 |
| `graph/nodes/dispatch.py` | 删 | `NormalizedReq` 能力并入系统提示 + tool 参数 |
| `graph/nodes/clarify.py` | 删 | 澄清改 `ask_user` tool；关卡/`MAX_CLARIFY_ROUNDS` 废弃 |
| `graph/nodes/retrieve.py` | 删 | fan-out 锚点不需要 |
| `graph/nodes/refine.py` | 删 | 局部修改由 ReAct + assemble/finalize 取代 |
| `graph/nodes/routing.py` | 删 | 规则路由废弃（路由权交 LLM） |
| `graph/nodes/answer.py` | 删 | QA 由 ReAct 循环 + agent 本体回复取代 |
| `graph/nodes/summarize.py` | 删 | 最终回复由 agent 本体输出，不再有收尾攻略节点 |
| `graph/nodes/memory.py` | 删 | 上下文装配由 checkpointer 的 messages 取代 |
| `graph/nodes/memory_update.py` | 删 | 消息追加由 agent 循环自动完成；receipt 不再需要 |
| `graph/nodes/weather.py` / `attractions.py` / `restaurants.py` / `transport.py` | 删 | 4 个检索节点逻辑并入对应检索 tool |

### 11.2 纯函数迁出后删文件

| 文件 | 迁出符号（保留，移入 tools/core） | 文件本身 |
|---|---|---|
| `graph/nodes/itinerary.py` | `cluster_by_day` / `_nearest_neighbor_order` / `_dist` / `DayPlan` 等 Pydantic schema / `_SYS` 编排提示 / `_build_payload` | 迁出后删 |
| `graph/nodes/budget.py` | `compute_budget` / `_sum_costs` / `_pick_cut_suggestions` / `_MAX_RETRY` | 迁出后删 |
| `graph/nodes/accommodation.py` | `overnight_days` / `attach_hotels` / `hotel_keyword` / `Hotel`·`_AccoResult` schema / `_SYS` | 迁出后删 |

### 11.3 保留并改写

| 文件 | 处理 |
|---|---|
| `graph/state.py` | 瘦身：保留 §4.1 业务字段；删废弃字段（若 `create_agent` 用自定义 state_schema，可能整体迁入新模块） |
| `graph/builder.py` | 重写为 §2.4 一行返回 `create_agent(...)` |
| `graph/stream.py` | 改 §5.2：token 过滤 + summary 取末条 AIMessage；契约事件不动 |
| `core/constants.py` | 清理：`NODES`/`NODE_LABELS` 精简；删 `MAX_CLARIFY_ROUNDS`；评估删 `EVENT_INTENT`；`EVENT_CLARIFY`/`EVENT_PLAN_PATCH`/`EVENT_TOKEN`/`EVENT_FINAL` 保留 |
| `tools/amap.py` | 复用，零改动 |
| `main.py` | 零改动（`build_graph(checkpointer)` 签名不变） |
