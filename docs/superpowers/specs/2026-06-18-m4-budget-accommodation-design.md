# M4 设计：住宿 + 预算闭环

- 日期：2026-06-18
- 里程碑：M4（住宿 + 预算闭环）
- 范围：后端新增 `accommodation` + `budget` 两节点 + 超支回退条件边；前端展示预算明细与超支提示、每日酒店卡
- 验收标准（策划书第八章）：完整 7 步编排跑通；超支能自动重排

## 决策摘要

| 决策点 | 选择 | 说明 |
|---|---|---|
| 费用来源 | LLM 估单价 + 后端算总账 | 系统无任何真实价格数据；itinerary/accommodation 由 LLM 估单价，budget 节点做纯函数汇总核算 |
| 数据模型 | 酒店嵌进每天（完整版，贴策划书 6.1） | `DayPlan.hotel` + `PlanItem.cost`，accommodation 把酒店并回 day_plans |
| 超支回退 | 混合：budget 给确定性建议 + itinerary LLM 重排 | budget 算超支额 + 挑「最贵可削减项」写入 `budget_advice`；回退时 itinerary 据此重排更省方案；`retry_count ≤ 2` 封顶 |
| 预算口径 | 总预算（元），`0` 表示不限 | 沿用 dispatch 的 `budget` 定义（总预算元，0=不限） |

## 1. 架构与图结构变化

在 M2 图（`clarify → dispatch → 4 并行 → itinerary → summarize`）里插入两个节点，并补一条超支回退条件边。**唯一改动的旧边**：删除 `itinerary → summarize`，改为下面链路。

```
... → itinerary → accommodation → budget ─┬─(over & retry<2)→ itinerary  (回退重排)
                                          └─(否则)──────────→ summarize → END
```

- `accommodation`：读 `day_plans` + `daily_centers`，用高德 POI 检索真实酒店候选，LLM 按**住宿档位 + 就近每日中心**为每个「过夜日」分配一家酒店并估每晚价，把 hotel 嵌回 `day_plans`。
- `budget`：**纯函数**。汇总 `day_plans` 内所有 `cost` + `hotel.price`，与总预算比较，产出 `budget_check`；自行判定本轮是否回退（见下「回退计数语义」），需回退时确定性挑出「最贵可削减项」写入 `budget_advice`。
- 回退时 `itinerary` 读 `budget_advice`，把「上轮超支 X 元、建议削减这些项」塞进 prompt，LLM 重排更省方案。最多回退 2 次，到顶带「已尽力压缩」说明进 summarize。

`builder.py` 改动：
- 新增 `g.add_node("accommodation", accommodation)`、`g.add_node("budget", budget)`。
- 删 `g.add_edge("itinerary", "summarize")`，加 `g.add_edge("itinerary", "accommodation")`、`g.add_edge("accommodation", "budget")`。
- 加 `g.add_conditional_edges("budget", route_after_budget, {"itinerary": "itinerary", "summarize": "summarize"})`。

### 回退计数语义（消除 off-by-one）

`retry_count` = 已发生的回退次数（初始 0）。**判定与计数都收在 budget 节点内**，路由只读一个布尔标志，不做算术，避免「递增放在哪」的跨轮歧义：

```python
# budget 节点内（伪码）
over = limit > 0 and estimated > limit
retry = over and state.get("retry_count", 0) < 2        # 本轮是否还要回退
new_retry_count = state.get("retry_count", 0) + (1 if retry else 0)
budget_check = {..., "over": over, "retry": retry, "retry_count": new_retry_count,
                "note": ("已尽力压缩，仍超出预算约 ¥{}".format(...) if over and not retry else "")}
return {"budget_check": budget_check, "retry_count": new_retry_count,
        **({"budget_advice": {...}} if retry else {})}

def route_after_budget(state) -> str:
    return "itinerary" if state.get("budget_check", {}).get("retry") else "summarize"
```

执行轨迹（始终超支的极端情形）：

| 轮次 | 进入时 retry_count | over | retry | 出口 retry_count | 路由 |
|---|---|---|---|---|---|
| 0（首算） | 0 | T | T | 1 | itinerary（回退 #1） |
| 1 | 1 | T | T | 2 | itinerary（回退 #2） |
| 2 | 2 | T | F | 2 | summarize（封顶 + note） |

即**最多回退 2 次**，`budget_check.retry_count` 最终为实际回退次数（前端「已自动重排 N 次」直接取它）。未超支时 `over=False → retry=False → summarize`，`retry_count` 保持 0。

## 2. 费用语义（消除歧义）

- `PlanItem.cost`：**人均**花费（元）。门票、餐标、市内交通均按人均；免费景点 / `transport` 项为 0。
- `Hotel.price`：**每晚整间价**（元，简化为按人数估的一间房）。
- 过夜日：`day ∈ [1, days-1]` 的天挂 hotel（最后一天离程不挂）；`days == 1` 时无酒店。
- **总额**：`estimated = num_people × Σ(items.cost) + Σ(hotel.price)`。
- **预算上限**：`limit = state["budget"]`（dispatch 已定义为总预算元）。`limit == 0` 表示**不限** → `over` 恒 `False`、永不回退。
- `over = limit > 0 and estimated > limit`。

## 3. 数据契约（后端 + 前端对齐）

### 3.1 itinerary 的 `PlanItem` 加费用字段（`backend/app/graph/nodes/itinerary.py`）

```python
cost: float = Field(default=0.0,
    description="该项人均花费(元)：门票/餐标/市内交通；免费景点或交通项填 0，沿用合理估算")
```

### 3.2 新增 `Hotel` + 把 hotel 嵌进 `DayPlan`

```python
class Hotel(BaseModel):
    name: str = Field(default="", description="酒店名称，沿用高德 POI 候选，不要编造")
    poi_id: str = Field(default="", description="高德 POI id；降级生成的参考酒店可留空")
    location: Location = Field(default_factory=Location, description="酒店经纬度")
    price: float = Field(default=0.0, description="每晚整间价(元)，按住宿档位估")
    level: str = Field(default="", description="住宿档位：经济/舒适/高端")

class DayPlan(BaseModel):
    ...                       # 现有字段不变
    hotel: Hotel | None = Field(default=None, description="当晚住宿；离程日或单日游为 None")
```

> `PlanItem` 已有 `model_config = {"populate_by_name": True}`（因 `from_` 别名）。`day_plans` 仍 `model_dump(by_alias=True)` 输出。

### 3.3 `budget_check` 结构（final 新增字段，前端展示）

```json
{
  "limit": 4000,
  "estimated": 3650,
  "over": false,
  "retry": false,
  "breakdown": {"ticket": 600, "hotel": 1400, "food": 1050, "transport": 600},
  "retry_count": 0,
  "note": ""
}
```

- `breakdown` 四类：`ticket`（attraction.cost × num_people 汇总）、`food`（meal.cost × num_people）、`transport`（transport.cost × num_people）、`hotel`（hotel.price 汇总）。
- `over`：是否超支（前端红色提示依据）。`retry`：路由标志（本轮是否回退，见第 1 节回退计数语义；前端可忽略）。
- `note`：到 retry 上限仍超支时填「已尽力压缩，仍超出预算约 ¥X」；否则空串。

### 3.4 State 新增（`backend/app/graph/state.py`）

取消注释并落定：

```python
budget_check: dict          # 见 3.3
retry_count: int            # budget 节点手动 +1；默认 last-write-wins，不用 add reducer
budget_advice: dict         # {"over_amount": float, "cut_suggestions": [..]}；itinerary 回退时读
```

hotels 不再单列字段，嵌在 `day_plans[i].hotel` 内。

### 3.5 前端类型（`frontend/src/types/index.ts`）

```ts
export interface Hotel { name: string; poi_id: string; location: LngLat; price: number; level: string }
export interface BudgetBreakdown { ticket: number; hotel: number; food: number; transport: number }
export interface Budget {
  limit: number; estimated: number; over: boolean
  breakdown: BudgetBreakdown; retry_count: number; note: string
}
// TripItem 加 cost?: number
// DayPlan 加 hotel?: Hotel | null
// FinalPayload 加 budget?: Budget
```

## 4. SSE 与前端展示

### 4.1 常量与桥接（`backend/app/core/constants.py`、`backend/app/graph/stream.py`）

- `NODES` 加 `"accommodation"`、`"budget"`。
- `NODE_LABELS` 加 `"accommodation": "正在挑选住宿…"`、`"budget": "正在核算预算…"`。
- `stream.py` final 分支：`budget = (snap.values or {}).get("budget_check", {})`，发出 `{"answer", "day_plans", "budget"}`。day_plans 已内含 hotel + cost，无需额外字段。

### 4.2 store 与消费层

- `stores/trip.ts`：加 `budget = ref<Budget | null>(null)` + `setBudget`；`setDayPlans` 清空时一并清 budget（或独立 `clearBudget`）。
- `composables/useSSE.ts` 的 `final` 分支：`tripStore.setDayPlans(...); tripStore.setBudget((data as FinalPayload).budget ?? null)`。
- `components/AgentProgress.vue` 的 `LABELS` 加 `accommodation: '挑选住宿'`、`budget: '核算预算'`。

### 4.3 ResultPanel.vue 新增两处

1. **预算总览条**（面板顶部、Day Tab 上方）：
   - 不限预算（`limit == 0`）：仅显示「已估 ¥{estimated}」。
   - 有预算：显示「已估 ¥{estimated} / 预算 ¥{limit}」；`over` 为 true 时整条红色 + 「⚠ 超支 ¥{estimated-limit}（已自动重排 {retry_count} 次）」；`note` 非空则展示。
   - 明细 `门票/住宿/餐饮/交通` 用小标签或可展开行呈现。
2. **每天酒店卡**：当天时间线末尾追加一张 🏨 酒店卡（名称 + 每晚价 + 档位），复用 `trip-card` 样式；`currentDay.hotel` 为 `null` 时不渲染。

## 5. 错误处理与降级

- 高德酒店 POI 检索失败 / 空 → accommodation 降级：LLM 仅按档位 + 每日中心坐标生成「参考酒店」（`poi_id` 留空、名称可标注参考），不阻断；价仍按档位估。
- LLM 估价异常 → `cost` / `price` 兜底为 0（budget 据此可能判不超支，可接受，不崩溃）。
- `limit == 0`（不限）→ 跳过超支判定，`over=false`，直接 summarize。
- 回退死循环防护：`retry_count ≤ 2` 硬上限，到顶强制 summarize + `note`。
- 前端：`budget` 为空（老会话 / 降级）→ 总览条不渲染，行程照常显示；`hotel` 为 null → 不渲染酒店卡。

## 6. 测试与验证（沿用 M2：pytest + 打桩，不依赖真实 Key/网络）

- `test_budget.py`：纯函数核算——未超支 / 超支 / `limit==0` 不限 / breakdown 四类分类正确 / 超支挑出 `cut_suggestions` / `retry_count` 到 2 封顶路由到 summarize。
- `test_accommodation.py`：POI 打桩 → 每个过夜日分到 1 家酒店、就近每日中心、价随档位、`days==1` 无酒店、POI 空走降级（参考酒店）。
- `test_itinerary.py`（扩展）：items 带 `cost`；回退场景下 `budget_advice` 进入 prompt（断言 prompt 含建议或重排后产出可被 budget 重新核算）。
- `test_builder.py`（扩展）：编译图含 `accommodation`/`budget` 节点 + budget 的超支条件边。
- `test_chat_stream_m4.py`：端到端 final 携 `budget` + day_plans 内含 hotel/cost；构造超支输入 → 触发回退 → 收敛（总额下降到限内）或封顶（带 note）。
- 前端：`bun run build`（vue-tsc + vite）类型契约即测试，须全绿。

### 手动验收路径

1. 输入带预算的完整需求（如「成都 3 天 2 人，预算 4000」）→ 走完编排。
2. final 后右侧面板顶部出现预算总览条（已估 / 预算 + 明细），每天时间线末尾出现 🏨 酒店卡。
3. 构造一个偏紧的预算（如「预算 1500」）→ 进度条可见 itinerary/accommodation/budget 重跑一轮 → 最终总额压入限内，或封顶显示「已尽力压缩」。
4. 不填预算 → 总览条只显示已估总额，无超支提示，不回退。

## 7. 不在本轮范围（YAGNI）

- `/api/plan/refine` 局部重排、地图点选新增 / 替换景点（留 M5）。
- 真实酒店报价 / 真实门票价 API（高德无，统一 LLM 估）。
- 预算明细的图表可视化（仅文字 + 标签条）。
- 多间房 / 房型细分 / 按晚不同酒店比价（统一「一间房估算」）。
