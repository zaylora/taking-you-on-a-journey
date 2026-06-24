# 设计：编排线性化简化（确定性图 + 可行性闸门）

- 日期：2026-06-24
- 范围：把当前 17 节点 / 6 条件边的 LangGraph 编排，收敛为一条 6 节点直线；新规划 / 改行程 / 问答三条业务链统一到一套 operations 模型；新增 preflight 可行性闸门，根治「依赖信息缺失却静默失败」一类 bug。算法（OR-Tools 排程）、高德封装、预算核算逻辑一行不动，只重构编排层。
- 与已有设计的关系：本方案**替代** `2026-06-24-single-agent-controlled-react-design.md`。那份是「重」方案（单 Agent ReAct，把"选哪个工具"交给 LLM）；经讨论确认痛点是**认知负担 + 维护成本**而非行为不可控，故改走「中」方案——保留确定性编排、不引入 LLM 选工具的不确定性。
- 验收标准：
  1. LangGraph 主拓扑收敛为 `START -> memory -> understand -> collect_context -> apply -> render -> memory_update -> END`，0 条件边。
  2. 新规划和改行程统一走 operations 模型；plan_new 表达为 `replace_plan` op，不再有独立的 plan/refine/answer 三条架构链。
  3. 每个 op 声明 required inputs；preflight 在 apply 前确定性校验，缺失且补不全时**不硬跑**，走 interrupt 反问或在 render 诚实回报。
  4. 「第一天改成黄埔」当 state 缺 city 时，不再静默生成雷同行程，而是先尝试反推 city、推不出则明确告知用户。
  5. 后端测试不依赖真实 LLM / 高德网络；前端仍能通过 SSE 收到进度与最终回复。

## 1. 背景与问题

当前后端是 LangGraph 固定图编排（[backend/app/graph/builder.py](../../../backend/app/graph/builder.py)）：

```text
memory -> dispatch_agent ->(clarify↺ / retrieve -> weather/attractions/restaurants/transport
        四路并行 -> enrich_duration 屏障 -> itinerary / refine / answer)
        -> accommodation -> budget↺ -> summarize -> memory_update
```

经逐节点排查，「太复杂」的真凶有三个，且**与节点总数关系不大**：

1. **四路并行 + fan-in 屏障**：[builder.py:50-56](../../../backend/app/graph/builder.py#L50) 用 6 行注释解释「为什么需要 enrich_duration 当同深度屏障防 day_plans 重复写」——拓扑复杂到要写注释。
2. **3 条靠标志位的隐式条件边**：`route_after_plan` / `route_after_accommodation` / `route_after_budget`（[routing.py](../../../backend/app/graph/nodes/routing.py)、[budget.py:93](../../../backend/app/graph/nodes/budget.py#L93)）全靠 `last_intent` + `refine_request.needs_*` 在 state 里隐式传递，读图看不出走向。
3. **30+ 字段的 state**（[state.py](../../../backend/app/graph/state.py)），其中 `weather/attractions/restaurants/transport/daily_centers/relax_level/retry_count` 等一大半只是节点间传值的中间态。

此外存在**第三类痛点**（用户实际遇到的 bug）：能力依赖的信息缺失时，节点硬跑且静默糊弄用户。典型例：

- 「第一天改成黄埔」→ `set_region` op → [refine.py:148](../../../backend/app/graph/nodes/refine.py#L148) `amap.geocode(f"{state.get('city','')}{area}")`。
- `city` 顶层字段**只在 plan_new 路径写入**（[dispatch_agent.py:144](../../../backend/app/graph/nodes/dispatch_agent.py#L144)），**refine 路径不写**。
- city 一空 → geocode 光秃秃的「黄埔」→ 定位错 / 失败 → 用户感知到「说了改但没变，也没人说为什么」。

## 2. 决策摘要

| 决策点 | 选择 | 说明 |
|---|---|---|
| 简化力度 | 中 | 只重构编排层；算法 / 高德 / OR-Tools / 预算逻辑不动 |
| 工具形态 | 形态 B（能力函数） | 检索能力降回普通函数，调度权归确定性代码，**不让 LLM 自由选工具** |
| 业务抽象 | 4 个职责单元 | understand / collect_context / apply / render，各是图节点但排成直线 |
| 节点粒度 | 6 节点直线 | 保住 Studio 可观测性 + checkpoint 断点，同时消除全部复杂度源（对比「3 节点黑箱」更平衡） |
| operations 统一 | plan_new 也是 op | `replace_plan` 表达新规划，三链合一 |
| 可行性闸门 | 工具声明 + 代码查 + LLM 说人话 | op 声明 required inputs，代码确定性校验缺失，LLM 只把「缺 X」翻成对用户的人话 |
| LangGraph | 保留为外壳 | 降级为「持久化 + 部署 + interrupt 澄清」外壳；澄清与闸门反问复用现有 `interrupt`，不重写 |
| SSE 进度 | 4 单元阶段 | 从「按节点名」改为按 understand/collect_context/apply/render 四档；节点级事件天然支持 |

## 3. 目标架构

### 3.1 图拓扑：17 节点 6 条件边 → 6 节点 0 条件边

```text
START
  -> memory            （会话记忆外壳，基本不动）
  -> understand        （解析 operations + preflight 闸门 + interrupt 澄清）
  -> collect_context   （按需并发取数）
  -> apply             （执行 operations，重算排程/住宿/预算）
  -> render            （出话 + 诚实回报跳过项）
  -> memory_update     （写回会话历史，基本不动）
  -> END
```

- 一条直线，0 条件边——从左读到右就是执行顺序，不用模拟超步调度。
- 与现在比：fan-in 屏障没了、空 `retrieve` 节点没了、3 条标志位条件边没了、`clarify↺` / `budget↺` 自循环没了。
- 4 个业务单元各是图节点（保 Studio 可观测 + checkpoint 断点），但它们**内部**调用的检索/排程/预算能力都是普通函数，不再是图节点。

### 3.2 「图节点 vs 普通函数」的边界

收敛后**只有 6 个图节点**。原 14 个业务节点（dispatch_agent、clarify、weather、attractions、restaurants、transport、enrich_duration、itinerary、accommodation、budget、refine、answer、retrieve、summarize）全部退回为普通函数，被对应的单元节点在内部按顺序调用。

- 图节点：签名 `(state, config) -> dict`，由 LangGraph 调度，输入输出走 state。仅 6 个。
- 普通函数：签名显式声明参数与返回值（如 `async def get_weather(city: str) -> dict`），由单元节点直接调用，看签名即知依赖。

## 4. 单元职责

| 单元（图节点） | 吸收的旧节点 | 职责 | 关键变化 |
|---|---|---|---|
| understand | dispatch_agent + clarify | 解析用户输入为 operations；preflight 校验依赖；缺信息走 interrupt 反问 | plan_new 也产出 op（`replace_plan`），三链合一 |
| collect_context | retrieve + weather + attractions + restaurants + transport + enrich_duration | 按 op 类型决定取多少数据，内部并发调高德封装 | 6 节点塌成 1 节点；并发用 `asyncio.gather`，不再靠图 fan-out |
| apply | itinerary + accommodation + budget + refine | 执行 operations，按规则重算排程/住宿/预算 | 「OR-Tools 全量重排」与「局部改一天」统一到一个执行器分支 |
| render | summarize + answer | 组织中文回复 + **诚实回报哪些 op 没做、为什么** | 闸门/apply 跳过的项必报，不漏报 |

> `memory` / `memory_update`（[memory.py](../../../backend/app/graph/nodes/memory.py)、[memory_update.py](../../../backend/app/graph/nodes/memory_update.py)）保留为外壳节点，本期不动。

## 5. operations 统一模型

新规划、改行程、问答统一表达为 operations 序列。复用现有 [refine_ops.py](../../../backend/app/graph/nodes/refine_ops.py) 的扁平 `Operation` 模型并扩展：

```python
class Operation(BaseModel):
    op: Literal[
        "replace_plan",      # 新增：全量（重）规划
        "set_region", "add_poi", "remove_poi", "replace_poi",
        "reorder", "set_pace", "set_budget", "set_hotel",
        "answer_only",       # 新增：不改计划，纯问答
    ]
    # ...沿用现有字段：day / area / query / kind / selector /
    #    strategy / direction / amount / days / criteria
    # replace_plan 复用 requirements 补丁承载 city/days/budget 等
    requirements_patch: dict = Field(default_factory=dict)
    question: str = ""       # answer_only：用户的问题
```

understand 产出 `operations: list[Operation]`；apply 顺序消费：

- 新规划「广州 3 天」→ `[{op: replace_plan, requirements_patch: {city:"广州", days:3}}]`
- 局部改「第一天改黄埔」→ `[{op: set_region, day:1, area:"黄埔"}]`
- 问答「为什么第二天这么赶」→ `[{op: answer_only, question:"..."}]`

这样三条链合一：路由不再靠 `last_intent` + 标志位，而是 apply 按 `op` 字面量分发。

## 6. preflight 可行性闸门

### 6.1 机制：工具声明 + 代码查 + LLM 说人话

每个 op 声明所需输入；preflight 确定性校验，分三步：

1. **声明**：op → required inputs 映射（见 6.2 依赖表）。
2. **校验 + 补救**：缺失字段先尝试确定性补救（如从 day_plans 坐标 / 会话历史反推 city）。
3. **裁决**：
   - 补全 → 放行，apply 正常执行。
   - 补不全 → **不硬跑**。要么走 interrupt 反问（信息可由用户补），要么标记该 op 为 `blocked` 交给 render 诚实回报（无法补且非必答）。

LLM 在闸门里**只负责一件事**：把「缺 city」这类机器判定翻译成对用户的自然语言反问（"我不确定当前是哪个城市，没法把第一天改到黄埔，方便说下城市吗？"）。判定本身是确定性代码，不交给 LLM。

### 6.2 op 依赖表（required inputs + 补救策略）

| op | required inputs | 缺失补救 | 补不全时 |
|---|---|---|---|
| replace_plan | city, days | city/days 从 requirements_patch / normalized_req / 会话历史取 | interrupt 反问（复用 clarify 逻辑） |
| set_region | city, area, 目标 day 存在 | city 从 day_plans 任一 item 坐标反推（geo→城市）或会话历史 | interrupt 反问 city |
| add_poi / replace_poi | 目标 day 存在, 该 day 有 center | center 从该 day stops 重算 | render 回报「第N天定位不到，未改」 |
| remove_poi | 目标 day 存在, selector 命中 | — | render 回报「未定位到要删的项」 |
| reorder | 目标 day 存在 | — | render 回报 |
| set_pace | 目标 day 存在 | — | render 回报 |
| set_budget | amount | — | render 回报「预算调整缺金额」 |
| set_hotel | 至少一个过夜日 | 过夜日由 day_plans 推导 | render 回报「无过夜日，无需酒店」 |
| answer_only | 无 | — | — |

> 这张表把现在散落在 refine 各分支里「事后塞进 skipped」的隐式判断，提前为「事前显式声明 + 必报」。

## 7. apply 执行语义

apply 按 op 顺序在 day_plans 工作副本上执行，统一收尾：

- `replace_plan`：调现有 OR-Tools 全量入口（[itinerary.py](../../../backend/app/graph/nodes/itinerary.py) 的 `itinerary` 逻辑改造为纯函数），消费 collect_context 产出的景点/餐饮池，重排全部天，再重算住宿（accommodation 逻辑）和预算（[budget.py](../../../backend/app/graph/nodes/budget.py) `compute_budget` 已是纯函数，直接用）。
- 局部 op（set_region / add_poi / …）：复用现有 [refine.py](../../../backend/app/graph/nodes/refine.py) `_apply_day_op` 系列逻辑，只改受影响天，按需重算交通/住宿/预算。
- 每个被结构修改的天统一 `_finalize_day`（剥旧交通段→重插交通→重算 center）。

输出结构化结果（沿用 refine 的诚实回报形状）：

```python
{
  "day_plans": [...],
  "changed_days": [1],
  "budget_check": {...},
  "applied": ["第1天已迁至黄埔（重排5项）"],
  "skipped": [],            # 含 preflight blocked 项的原因
  "needs_clarification": "",
}
```

## 8. collect_context 按需取数

不再四路并行图 fan-out，改为 apply 决策前按 op 类型确定性地取数：

| op | 取数范围 |
|---|---|
| replace_plan | 全量：天气 + 全城景点池 + 餐饮池（喂 OR-Tools） |
| set_region | 仅目标区域：geocode(area) → 围绕新 center 查景点/餐饮 |
| add_poi / replace_poi | 仅目标 day center 附近查 POI |
| reorder / set_pace / remove_poi / set_budget / set_hotel | 不取数（纯本地重排/重算） |
| answer_only | 不取数 |

内部并发用 `asyncio.gather`（如全量时天气/景点/餐饮并发），不依赖 LangGraph 超步。

## 9. LangGraph 与 SSE 影响

### 9.1 LangGraph 角色降级

LangGraph 从「编排引擎」降为「外壳」，但仍扛三样自写都很痛的事，故保留：

- **interrupt 澄清**：[stream.py](../../../backend/app/graph/stream.py) 用 `Command(resume=...)` + `aget_state().tasks[].interrupts[0].value`。understand 的澄清和 preflight 的反问**复用现有 [clarify.py](../../../backend/app/graph/nodes/clarify.py) 的 interrupt 逻辑**，不重写。
- **checkpointer 多轮持久化**：`make_graph` 交平台注入、按 thread_id。
- **平台部署**：[langgraph.json](../../../backend/langgraph.json) 注册 `trip: make_graph`。

### 9.2 SSE 进度

[stream.py](../../../backend/app/graph/stream.py) 现在靠 `on_chain_start/end` + `name in NODES` 按节点名发进度，靠 `metadata.langgraph_node=="summarize"` 放行 token。收敛后：

- 进度天然变成 6 节点（其中 4 个业务单元）的节点级事件——**仍走现有 `on_chain_start/end` 机制**，只需把 `NODES` / `NODE_LABELS` 改为新单元名。
- token 放行从 `=="summarize"` 改为 `=="render"`。
- 前端 `AgentProgress.vue` 进度标签改为 understand/collect_context/apply/render 四档；旧标签可暂留兼容。

> 注：因 4 单元各是独立图节点（非塌进单一 orchestrate），SSE 进度无需在节点内部手动发自定义事件，沿用节点级事件即可。这是选 6 节点而非 3 节点的额外收益。

## 10. state 瘦身

第一阶段不大删字段（降风险），先**统一入口**：所有顶层需求字段（city/days/num_people/budget/preferences）一律通过 `normalized_req` 读写，杜绝 plan_new 写顶层、refine 读顶层却没人写的割裂（city bug 根因）。

第二阶段再把纯中间态字段从主 state 移走：

- 移除：`weather / attractions / restaurants / transport / daily_centers / relax_level / retry_count / refine_request` → 降为 collect_context / apply 的局部变量或返回值。
- 保留（需跨轮持久化）：`messages / conversation_summary / normalized_req / day_plans / budget_check / plan_version / changed_days / clarify_history / dropped_attractions`。

## 11. 迁移计划（分步、每步可独立测试提交）

### 阶段 1：operations 模型扩展 + preflight
- [refine_ops.py](../../../backend/app/graph/nodes/refine_ops.py) `Operation` 增加 `replace_plan` / `answer_only` + `requirements_patch`。
- 新增 `backend/app/planning/preflight.py`：op 依赖表 + 确定性校验 + city 反推补救。
- 单测：依赖表每个 op 的校验与补救；city 反推。

验证：`cd backend && uv run pytest tests/test_preflight*.py`

### 阶段 2：能力函数化（不改图）
- 把 weather/attractions/restaurants/transport 节点逻辑抽为 `app/planning/context.py` 的纯函数（`collect_context(req, operations)`）。
- 把 itinerary 全量逻辑、refine 局部逻辑、accommodation、budget 整理为 `app/planning/apply.py` 的纯函数（保留原算法，仅去掉 state 包装）。
- 单测：迁移 `test_parallel_retrieval` → context 函数测试；refine 测试指向 apply。

验证：`cd backend && uv run pytest tests/test_context*.py tests/test_apply*.py`

### 阶段 3：4 单元节点 + 切图拓扑
- 新增 `understand` / `collect_context` / `apply` / `render` 四个单元节点（薄壳，调阶段 2 的纯函数）。
- 改 [builder.py](../../../backend/app/graph/builder.py) 为 6 节点直线，删除 6 条件边。
- 改 [stream.py](../../../backend/app/graph/stream.py) 的 `NODES` / token 放行节点名。
- understand 复用 clarify 的 interrupt。

验证：`cd backend && uv run pytest tests/test_linear_topology.py tests/test_chat_stream.py`

### 阶段 4：迁移多轮测试 + 前端进度
- `test_multiturn_*` 改为走新链路；`test_refine_*` 指向 apply。
- 前端 `AgentProgress.vue` 进度标签四档。

验证：`cd backend && uv run pytest`

### 阶段 5：清理旧节点 + state 瘦身
- 删除已无引用的旧节点文件（dispatch_agent / clarify / weather / attractions / restaurants / transport / enrich_duration / retrieve / itinerary 节点壳 / accommodation 节点壳 / budget 节点壳 / refine / answer / summarize / routing）。
- `rg` 确认无引用后再删；执行 state 第二阶段瘦身。

验证：`rg -n "dispatch_agent|route_after_|enrich_duration" backend/app backend/tests && cd backend && uv run pytest`

## 12. 测试策略

三层组织：

1. **schema 层**：`Operation` 扩展字段、序列化形状。
2. **能力函数层**：context / apply / preflight 纯函数，不依赖真实网络（沿用现有高德/LLM 打桩）。
3. **单元节点 + 图层**：4 单元节点决策、interrupt 澄清、SSE 输出、memory 更新。

关键用例：

- 新规划广州 3 天：全量生成（replace_plan）。
- 第一天改黄埔（state 有 city）：只改第 1 天。
- **第一天改黄埔（state 缺 city）：preflight 先反推→推不出则反问 city，不静默生成雷同行程。**（直接覆盖原 bug）
- 预算改 3000：先重算预算，不无条件重排。
- 第二天加博物馆：只重排第 2 天。
- 「为什么第二天这么赶」：answer_only，不改计划。
- op 部分失败：render 诚实回报 applied / skipped。

## 13. 风险与缓解

| 风险 | 缓解 |
|---|---|
| apply 变大 | 按 `schemas/context/apply/preflight/validation` 拆文件；内部纯函数单测覆盖 |
| operations 统一引入回归 | replace_plan 直接复用现有 OR-Tools 入口，局部 op 复用现有 refine 逻辑，不重写算法 |
| 切图导致旧测试大量失效 | 分阶段：能力先函数化并测通，再切图，旧节点最后删 |
| SSE/前端进度断裂 | 4 单元仍是节点级事件，沿用现有机制；前端旧标签暂留兼容 |
| city 反推不可靠 | 反推失败一律 fallback 到 interrupt 反问，绝不静默继续 |

## 14. 非目标

- 不引入 LLM 自由选工具（保持确定性编排）。
- 不彻底删除 LangGraph。
- 不让 LLM 直接生成完整 day_plans 替代 OR-Tools 排程。
- 不重写高德封装 / 排程算法 / 预算核算逻辑。
- 不做跨城市多目的地联程、真实酒店预订链路。

## 15. 推荐实施顺序

```text
operations 扩展 + preflight
  -> 能力函数化（context / apply）
  -> 4 单元节点 + 切 6 节点直线图
  -> 多轮测试迁移 + 前端进度
  -> 清理旧节点 + state 瘦身
```

每步独立测试、独立提交。不在同一改动里同时切图、删旧节点、改前端。
