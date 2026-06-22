# M6 重做设计：itinerary 以 OR-Tools VRPTW 联合优化 + 真实距离矩阵

- 日期：2026-06-22
- 里程碑：**M6 重做（v2）**——在 `m6-v2` 分支上，用「OR-Tools 联合求解 + 高德真实距离矩阵」整体重构 itinerary 节点，取代 `m6` 分支的「两段贪心启发式」实现
- 范围：**后端 itinerary 子系统重构**——前端零改动（几何契约不变，分段路线照常绘制）
- 基线：`m6` 分支已完整实现「算法主导几何 + LLM 软填」的启发式管线（KMeans 聚类 + 评分预选 + 时间预算再平衡 + 最近邻顺路）；本设计**替换其算法内核、保留其对外契约**

---

## 0. 动机与根因

### 0.1 现状（`m6` 分支）

`m6` 已是一个质量不错的「启发式约束优化管线」：

```
attractions
  → enrich_duration   (Tavily 估 visit_minutes，降级静态表)
  → select_by_rating  (按评分装进总时间预算，宁缺勿滥，产 dropped_attractions)
  → cluster_kmeans    (KMeans 地理聚类，纬度等距投影，降级方位角贪心)
  → rebalance_by_budget (超预算的天弹出最低分景点 → 塞进地理最近的余量天)
  → build_day_stops   (顺路插就近午/晚餐)
  → insert_transport  (每跳按直线距离定 mode + 估 cost)
  → merge_soft_fields (LLM 只填 start/end/cost/indoor/note，几何全锁死)
```

### 0.2 三大质量痛点（用户确认）

1. **路线绕路 / 顺序乱、跨天分配不合理**：分天（KMeans 只看地理）与顺路（最近邻）是两段独立的局部贪心，各自只优化一个维度，合起来非全局最优。
2. **距离 / 交通不真实**：全程用直线 `haversine`，与真实路网（跨江、绕山）差异大；交通方式与耗时按直线距离粗估。
3. **时间安排不合理**：营业时间（opentime）只作为「软填参考」塞给 LLM，**未进硬约束**，可能排出「到了没开门 / 已闭馆」。

### 0.3 架构痛点

`itinerary.py` 448 行，多段贪心彼此纠缠（如 `rebalance_by_budget` 的预算闸门要与下游 `day_used_minutes` 同口径），难维护。

### 0.4 根因

> 「分天、顺路、时间窗、真实距离」被拆成几个**独立的局部贪心步骤**，每步只看一个维度、用直线距离凑合，没有任何一步能同时权衡这几件事。

**结论**：把这四维揉成**一个带时间窗的车辆路径问题（VRPTW）联合求解**，喂入高德真实距离矩阵。这是符合本项目 CLAUDE.md「依赖优先原则」的选择——成熟开源求解器（Google OR-Tools），而非手写优化算法。

---

## 1. 决策摘要

| 决策点 | 选择 | 说明 |
|---|---|---|
| 核心算法 | **OR-Tools `constraint_solver`（Routing/VRP 库）** | 旅游规划天然是 VRPTW；Routing 库内置 disjunction、time dimension、元启发式。替掉 `select_by_rating`+`cluster_kmeans`+`rebalance_by_budget`+`_nearest_neighbor_order` 四个函数 |
| 距离数据 | **高德 `v3/distance` 真实街道时间** | N 起点→1 终点，调 N 次凑 N×N 矩阵；替掉直线 haversine（haversine 降级为兜底） |
| 矩阵规模 | **评分粗筛到上限 → 对这批调全矩阵** | 高德普通 Web Key 无「一次拿 N×N」接口，凑全矩阵需 N 次请求。粗筛把候选从几十收口到十几个，把调用量从 O(几十²) 压到 O(十几²) |
| 景点取舍 | **粗筛砍垫底 + OR-Tools 丢弃惩罚做边界精筛** | prefilter 只砍评分明显垫底、绝无可能排进的；装得下边界上「丢哪个」交 OR-Tools disjunction 惩罚（高评分→高惩罚→尽量不丢） |
| 求解降级 | **矩阵层降直线 + 求解层放松约束重解** | 高德矩阵单弧失败→该弧用 haversine 估时；求解无可行解→三级放松（时间窗→预算→去窗）重解。**不保留 m6 启发式作兜底** |
| 架构边界 | **整个 itinerary 重构** | 算法抽到新子包 `app/itinerary/`，节点 `itinerary.py` 瘦身为纯编排；下游用 re-export 保护，零改动 |
| refine 边界 | **refine 不触发 OR-Tools** | 维持 M5「改一天只动一天」的局部编辑体验；OR-Tools 仅在 plan_new 与 budget 超支回退时运行 |

### 1.1 依赖可用性验证（2026-06-22 实测）

在本机（Windows 10 + Python 3.12.6 + uv）实测：`uv run --with ortools` 安装 `ortools 9.15.6755`（含 numpy 共 10 包，421ms）。跑最小 VRPTW demo，验证建模所需的 5 个特性全部工作：

- ✅ 多车辆（= 多天）从 depot 出发，各分到景点并顺路排序
- ✅ time dimension：弧成本（交通时间）+ service time（游玩时长）
- ✅ 时间窗（营业时间）约束被尊重
- ✅ disjunction：可选节点 + 丢弃惩罚（rating 越高惩罚越大）
- ✅ 放松约束重解：极紧时间窗导致全丢弃 → 放宽时间窗后成功出解

**设计不建立在未验证的依赖假设上。**

---

## 2. OR-Tools VRPTW 建模

### 2.1 模型映射（旅游规划 → VRP 术语）

| 旅游概念 | VRP 建模 |
|---|---|
| 候选景点（预筛后十几个） | 节点 node |
| 旅行天数 days | 车辆数 vehicles（每天 = 一辆车） |
| depot（出发/收尾点，见 2.4） | 共同 depot |
| 景点间真实街道时间（高德矩阵） | 弧成本 arc cost（分钟） |
| 每个景点游玩时长 visit_minutes | 节点 service time（注入 time dimension） |
| 每天可用时长 DAY_BUDGET（480 分） | 每辆车 time dimension 上界 |
| 营业时间 opentime | 节点 time window [开门, 关门] |
| 「高分景点尽量别丢」 | 每节点一个 disjunction，丢弃惩罚 = f(rating) |
| 目标 | 最小化（总旅行时间 + 丢弃惩罚总和） |

### 2.2 求解参数

- `FirstSolutionStrategy.PATH_CHEAPEST_ARC`（首解）
- `LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH`（元启发式）
- `time_limit = 5s`（收在 constants，便于调）
- 固定参数保证可复现（求解确定性取决于策略 + 参数，测试只断言结构性质，不断言精确路径）

### 2.3 求解产出 → day_plans

- 车辆 k 的访问序列 = 第 k 天的有序景点 → 喂给 `build_day_stops`（就近插餐厅）+ `insert_transport`（插交通段）。
- 未被任何车辆访问的节点（disjunction 被丢弃）= `dropped_attractions` 的「精筛」部分，reason = 「综合距离/时间/评分权衡后未排入」。

### 2.4 depot 处理

- **plan_new**：depot = 城市中心（候选景点质心）或城市 geocode 中心。每天从 depot 出发、回到 depot（VRP 默认闭合回路）。MVP 接受「回到中心」的近似——它对路线形状影响小，且简化建模。
- **多天酒店换点**：M6 不强连酒店（沿用 m6 决策——交通段只在停靠点间插入，首尾不接酒店）。跨天酒店腿不产生，depot 闭合回路只用于求解内部的距离约束，不画进总览路线。
- 跨城行程：超出 M6 范围（MVP 单城）。

### 2.5 三级放松约束重解

`time_limit` 内若返回无可行解（通常因时间窗太紧），按固定层级放松后重解，每层重解一次，记录放松级别 `relax_level`：

1. **L1 放宽时间窗**：所有节点 time window → [0, DAY_BUDGET]（忽略营业时间）
2. **L2 放宽每日预算**：DAY_BUDGET → DAY_BUDGET × 1.5
3. **L3 去时间维度**：退化为纯 TSP/VRP（只保顺路，不保时间）

`relax_level` 写入 state（可选），供前端提示「因时间紧张，部分营业时间约束已放宽」。

---

## 3. 模块拆分与文件结构

```
backend/app/graph/nodes/
├── itinerary.py          ★瘦身：只剩 itinerary() 节点编排（<100 行）
│                          流程：预筛 → 取矩阵 → 求解 → 装配 → 软填 → 返回
│                          re-export 下游依赖的符号（见 3.2）
├── time_budget.py        保留：attraction_minutes / transit_minutes / day_used_minutes
│                          （refine 与 optimizer 都用；惰性导入断循环依赖）

backend/app/itinerary/    ★新增子包（算法与节点解耦，纯逻辑可单测）
├── __init__.py
├── geometry.py           迁入：haversine_km / mode_by_distance / insert_transport
│                          / build_day_stops / pick_nearest / default_cost_by_mode
├── matrix.py          ★新：distance_matrix(points) — 调高德 v3/distance 凑 N×N
│                          + SQLite 持久缓存（poi_id 对为键）+ 失败降级 haversine
│                          + asyncio.Semaphore 限并发
├── prefilter.py       ★新：select_candidates(attractions, days) — 评分粗筛到上限
│                          产 dropped 的「粗筛」部分
├── optimizer.py       ★新：solve_vrptw(matrix, nodes, days, ...) — OR-Tools 求解
│                          含三级放松；返回 (per_day_routes, dropped_nodes, relax_level)
├── assembler.py       ★新：routes_to_day_plans(...) — 求解结果 → skeleton_days
│                          （调 build_day_stops + insert_transport）
├── soft_fill.py          迁入：merge_soft_fields + LLM 软填 payload 构造 + 调用
└── schemas.py            迁入：DayPlan / PlanItem / Location / Hotel / DayWeather
```

### 3.1 设计原则

- **节点只做编排，算法全在 `app/itinerary/` 子包**：每个算法模块零 I/O（除 matrix 调高德），纯函数、可独立单测。复杂度被切成小块，每块一个职责。

### 3.2 对外接口零破坏（re-export）

下游依赖（调研已确认）：
- `refine.py`：`from app.graph.nodes.itinerary import haversine_km, insert_transport`（+ 从 time_budget 导 `attraction_minutes`/`day_used_minutes`）
- `accommodation.py` / `answer.py` / tests：依赖 `DayPlan`/`PlanItem` 等数据类

重构后这些符号从新位置 **re-export 回 `itinerary.py`**：

```python
# itinerary.py 顶部
from app.itinerary.geometry import haversine_km, insert_transport  # re-export
from app.itinerary.schemas import DayPlan, PlanItem, Location, Hotel, DayWeather  # re-export
```

下游 import 路径一行不用改。

### 3.3 被删除的 m6 函数

`select_by_rating`（→ 拆成 prefilter 粗筛 + optimizer disjunction 精筛）、`cluster_by_day` / `cluster_kmeans`（→ optimizer 车辆分配）、`rebalance_by_budget`（→ optimizer time dimension 上界）、`_nearest_neighbor_order`（→ optimizer 路由优化）。对应单测同步迁移/重写（见 §5）。

### 3.4 依赖变更

- `pyproject.toml` 新增 `ortools`（实测 9.15.6755 可用）。
- `scikit-learn` 若仅被 `cluster_kmeans` 使用，重构后可移除（待确认无其他引用）。

---

## 4. 数据流与缓存设计

### 4.1 重构后 itinerary() 节点执行流

```
输入：state.attractions（已含 visit_minutes/rating/opentime，enrich_duration 产出）

1. prefilter.select_candidates(attractions, days)
     → 评分粗筛到上限 MAX_CANDIDATES = days × PER_DAY_CAP × 系数（如 3天×5×1.5 → 收口到 ~15）
     → 返回 (candidates, dropped_prefilter)

2. depot = 城市中心（质心）或城市 geocode 中心
   nodes = [depot] + candidates

3. matrix.distance_matrix(nodes)            # ★调高德，带缓存
     → N×N 真实街道时间矩阵（分钟）；任一弧失败 → haversine 估时兜底

4. optimizer.solve_vrptw(matrix, nodes, days, day_budget=DAY_BUDGET)
     → 建 RoutingModel → time dimension（service time + 时间窗）→ disjunction（rating→惩罚）
     → 求解（time_limit=5s）→ 无解则三级放松重解
     → 返回 (per_day_routes, dropped_nodes, relax_level)

5. assembler.routes_to_day_plans(per_day_routes, state)
     → 每天：build_day_stops（就近插餐厅）→ insert_transport（插交通段）
     → skeleton_days + daily_centers

6. soft_fill：LLM 填 start/end/cost/indoor/note → merge_soft_fields（几何锁死）

7. 返回 state patch：
     day_plans, daily_centers,
     dropped_attractions = dropped_prefilter + dropped_nodes（带 reason），
     plan_version+1, changed_days, relax_level（可选，§2.5）
```

### 4.2 距离矩阵缓存（配额命脉）

- **缓存键**：`(poi_id_a, poi_id_b)` 有序对 → 真实时间（分钟）。用 poi_id 不用坐标（浮点不稳；poi_id 跨会话稳定）。
- **存储**：`backend/data/` 下 SQLite（与 checkpoints 同目录、不同表 `distance_cache`），`(poi_a, poi_b)` 主键。城市内 POI 间街道时间几乎不变，设 30 天 TTL 防 POI 迁移/道路变化。
- **调用收敛**：① 对称复用（a→b ≈ b→a，只存一半）；② 跨会话命中（同城热门景点矩阵大面积复用）。首次规划新城 ~N 次高德请求，之后近乎零调用。
- **限速**：`asyncio.Semaphore`（≤3 并发）避开高德 `CUQPS_HAS_EXCEEDED_THE_LIMIT`；失败弧不阻断，降级 haversine。
- **复用现有范式**：沿用 `amap.py` 的统一 httpx 5s 超时 + 失败降级不抛 + `@traceable` + key 不下发。

### 4.3 与 refine 的协同

refine 改某天点后，靠 `insert_transport`（re-export 保留）重派生交通段 + `day_used_minutes` 校预算，**不触发 OR-Tools 全量重解**。OR-Tools 只在 plan_new 与 budget 超支回退时跑。保持 M5「改一天只动一天」的体验不破。

### 4.4 图结构

**不变**。itinerary 在图中的上下游不动：`enrich_duration → itinerary → (route_after_plan) → accommodation/budget/summarize`，budget 超支回环 `→ itinerary` 不变。改动全在节点内部。

---

## 5. 测试策略

### 5.1 必须保持的不变量（现有测试已钉死，重构后仍通过）

- `items[0].type != "transport"` 且 `items[-1].type != "transport"`（首尾是停靠点）
- 每天 `交通段数 == 停靠点数 - 1`（每对相邻点恰好一段，无悬空）
- 交通段 `from/to/location` 与相邻停靠点对齐
- 软填只动 `start/end/cost/indoor/note`，poi_id/坐标/顺序由算法锁死，LLM 失败降级骨架
- `day_plans` / `dropped_attractions` / `daily_centers` state 字段结构契约不变

### 5.2 新增测试（纯函数零 I/O 优先）

| 模块 | 测什么 |
|---|---|
| `prefilter` | 评分降序砍到上限、确定性（同分按 poi_id）、dropped 带 reason、点数<上限全保留 |
| `matrix` | mock 高德响应：N×N 组装正确、对称复用、单弧失败降级 haversine、缓存命中不重复调用、Semaphore 限并发 |
| `optimizer` | **核心**：小矩阵 → 每天序列顺路、时间窗被尊重（到点在营业时间内）、高分点不被丢、days 辆车都用上；三级放松：构造无解输入（时间窗全冲突）断言逐级放松后出解、relax_level 正确 |
| `assembler` | 路由序列 → day_plans：餐厅就近插入、交通段 mode 与真实距离匹配 |
| 集成回归 | 广州 3 天 case（mock matrix + search_around）：餐厅贴景点、无折返、每跳有段、dropped 可解释 |

### 5.3 OR-Tools 测试特殊处理

固定 `FirstSolutionStrategy` + 参数；断言**结构性质**（顺路、时间窗、不丢高分）而非**精确路径**（求解器版本升级可能微调路径）——避免测试脆弱。

### 5.4 端到端验收（人工）

真实跑广州/成都 3 天：① 同天景点顺路无回头；② 餐厅贴当天景点；③ 交通段距离/方式用真实街道时间且合理；④ 景点到点在营业时间内；⑤ 总览路线连续、按天配色、无怪线。

---

## 6. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| 高德 distance 配额/QPS 超限 | 矩阵不全 | SQLite 持久缓存 + 对称复用 + Semaphore 限速；单弧失败降级 haversine（不阻断） |
| OR-Tools 求解超时/无解 | 出不了行程 | time_limit 兜底 + 三级放松约束重解；放松到 L3（纯顺路）几乎必有解 |
| 评分粗筛砍掉了本可排进的点 | 行程质量降 | 上限设宽松系数（×1.5），只砍明显垫底；精筛交 OR-Tools |
| 真实街道时间矩阵不对称（单行道等） | 路线略偏 | 接受不对称（分别存 a→b、b→a 时不做对称复用）；MVP 可对称近似换配额，列为可调 |
| depot 闭合回路引入「回中心」虚距离 | 末点选择略偏 | 影响小（仅求解内部约束，不画线）；M7 可改开放式路径（不强制回 depot） |
| ortools 体积大（22.8MiB）/ 编译扩展 | 部署变重 | 实测 Windows 可装；符合 CLAUDE.md 依赖优先（成熟开源胜过手写优化） |
| 重构打断下游 | refine/budget/accommodation/answer 失效 | re-export 保护 import；现有不变量测试守护契约 |

---

## 7. 落地分支与里程碑

- **基线分支**：当前在 `m6-v2`（从设计文档提交 `cc93d9a` 拉出、零实现）。`m6` 分支有完整启发式实现。
- **建议**：本设计在 `m6-v2` 上实现。是否先把 `m6` 的「保留部分」（geometry / soft_fill / schemas / time_budget / enrich_duration / amap.search_around）cherry-pick 或合并过来作为起点，由实现计划阶段决定（避免从零重写已验证的几何代码）。
- 里程碑编号沿用现有 M6（路线规划），本设计是 M6 的算法内核升级，不改总里程碑表。

---

## 8. YAGNI / 范围边界

- ❌ 不做跨城行程（MVP 单城）
- ❌ 不做开放式路径 / 酒店强连（M7 可选增强）
- ❌ refine 不接 OR-Tools（维持局部编辑）
- ❌ 不保留 m6 启发式作 fallback（降级靠矩阵层 haversine + 求解层放松）
- ✅ 只聚焦：用 VRPTW 联合优化「选点+分天+顺路+时间窗」+ 真实距离矩阵 + 整体模块重构
