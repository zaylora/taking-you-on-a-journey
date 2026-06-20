# M7：时间预算驱动的合理行程编排

日期：2026-06-21
状态：设计已确认，待写实现计划

## 背景与问题

当前行程编排（`backend/app/graph/nodes/itinerary.py`）由 M6 重构而来，"算法主导几何、LLM 只填软字段"。但存在两个让行程不合理的根因：

1. **没有每日时间预算**：一天排几个景点纯靠 `cluster_by_day` 的 `景点数 ÷ 天数` 均衡切片（`itinerary.py:233-241`）。一天能不能逛得完（停留 + 用餐 + 路上耗时是否 ≤ 当天可用时间）算法完全不管，`start`/`end` 还是 LLM 事后瞎估的软字段，不校验。→ **塞太多**。

2. **聚类为了数量均衡牺牲地理紧凑**：`cluster_by_day` 按到城市质心的方位角排序后均衡切片，为了让每天景点数相等，会硬把较远的点塞进同一天。→ **走太远**。

此外现有高德调用未带 `extensions=all`（`amap.py:39-43`），评分、人均、营业时间都没拉取，无从做"宁缺勿滥"的取舍。

## 目标

- 引入**每日时间预算**，一天只排逛得完的量（约 3–4 个景点 + 2 顿饭）。
- 同一天的景点**地理紧凑**，少走路。
- 天数固定时**宁缺勿滥**：按评分取舍，砍掉低分/装不下的景点并向用户说明。
- 景点游玩时长用 **LLM + Tavily 联网**查真实建议时长，降级到静态类型表。

## 已确认的关键决策

| 决策点 | 选择 |
|---|---|
| 天数固定时景点装不下 | 按评分/热度取舍，宁缺勿滥（记 `dropped_attractions`） |
| 游玩时长来源 | LLM 联网（Tavily）查真实建议时长，降级静态类型表 |
| Tavily 形态 | 做成独立可复用工具，绑给编排 agent，由 agent 决定何时联网 |
| 核心编排算法 | 方案 C：评分预选 + 地理聚类(KMeans) + 预算校验再平衡 |

## 设计 1：数据富化层

### 高德侧（`backend/app/tools/amap.py`）
- `search_poi` / `search_around` 增加 `extensions=all`，从 `biz_ext` 解析：
  - `rating`（评分 0–5）→ 取舍依据
  - `cost`（人均）→ 接入（已有字段但未用）
  - `opentime`（营业时间文本）→ 晚到/早闭校验
- 每个景点 dict 从 `{name, poi_id, lng, lat, address, type}` 扩为额外带 `rating / cost / opentime / typecode`。
- 字段缺失给安全默认：`rating=0.0`、`opentime=""`、`cost=0.0`。

### Tavily 工具（新增 `backend/app/tools/web_search.py`）
- 加依赖 `langchain-tavily`，配置 `tavily_api_key`（`SecretStr`，沿用 amap key 的安全约束：不下发前端、不进日志/SSE）。
- 封装成一个 LangChain 工具（`@tool` 或 `TavilySearch`），职责：给定景点名/查询返回联网摘要。**工具本身 provider 无关、可复用**。

### 时长富化（新增节点 `backend/app/graph/nodes/enrich_duration.py`）
- 一个 ReAct/tool-calling agent，绑定上面的 Tavily 工具，在分天**之前**对候选景点估 `visit_minutes`（整数分钟）。
- agent 自己决定是否/对哪些景点联网查（知名景点可直接给、拿不准的才查）。
- 产出写进每个景点 dict 的 `visit_minutes`。
- **降级**：Tavily 未配 key 或 agent 失败 → 落静态类型映射表（按 `typecode`）：博物馆 150 / 主题乐园 240 / 公园 120 / 观景台·广场 60 / 寺庙 60 / 默认 90 分钟。保证算法永远有时长可用。

关键：**时长是"硬数据"，聚类前备齐**，不再是 LLM 事后瞎估的软字段。

## 设计 2：时间预算模型（纯函数，置于 itinerary.py 或新 `time_budget.py`）

- `DAY_BUDGET` 常量：每天可游玩分钟数（默认 480 = 8h，09:00–18:00 扣午餐占用）。
- 用餐占用：午餐 60min、晚餐 60min（晚餐在末尾，不一定计入硬预算）。
- `transit_minutes(km, mode)`：按交通方式估耗时（步行 ~12km/h、公交含等待 ~15km/h、驾车 ~30km/h 市内）。
- `attraction_minutes(p)`：取 `p["visit_minutes"]`，缺失用静态表。
- `day_used_minutes(items)`：累加当天所有景点停留 + 餐饮占用 + 相邻段交通耗时。

## 设计 3：编排算法（方案 C，替换 `cluster_by_day`）

三步纯函数，可单测：

### 第一步：全局评分预选（治"塞太多/宁缺勿滥"）
- 候选景点按 `rating` 降序（评分相同按距市中心近优先，保证确定性）。
- 总预算闸门 `总可用 = days × DAY_BUDGET`。
- 从高分往下装，每装一个累加 `visit_minutes + 该景点引入的平均餐饮/交通开销估值`，装满总预算即停。
- 砍掉的进 `dropped_attractions`（`name / rating / reason`）。

### 第二步：地理聚类成天（治"走太远"）
- 对预选景点用 **scikit-learn `KMeans(n_clusters=days)`** 按经纬度聚类（依赖优先原则，符合 CLAUDE.md）。
- 经纬度先做等距投影（按纬度 `cos(lat)` 缩放经度），避免高纬度经度被高估。
- KMeans 不保证每群大小均衡 → 第三步再平衡。

### 第三步：每日预算复校 + 再平衡
- 每群算 `day_used_minutes`。
- **超预算天**：弹出该天评分最低景点 → 尝试塞进地理最近且有余量的相邻天；塞不进进 `dropped_attractions`。
- **过少天**：从相邻超载天借一个最近点。
- 收敛后每天内部用现有 `_nearest_neighbor_order` 排序，复用 `build_day_stops`（就近餐饮）+ `insert_transport`（交通段）。

### 降级
- KMeans 不可用（sklearn 未装/景点数 < days）→ 回退现有方位角切片 + 预算校验。

产出仍是 `skeleton_days`，后接 LLM 软填（此时只填 cost/note/indoor，时长已是硬数据）。

## 设计 4：数据流串联、降级与验证

### 节点编排顺序
```
attractions(检索 + extensions=all 富化评分/营业时间)
  → enrich_duration(新增：Tavily agent 查 visit_minutes)
  → itinerary(预选 → KMeans 聚类 → 预算复校再平衡 → 算时间 → LLM 软填)
  → budget / weather / accommodation(已有，不动)
```

### 字段流转
- `attractions[]` 每项新增 `rating / cost / opentime / visit_minutes`。
- itinerary 产出新增 `dropped_attractions[]`，answer 节点可向用户说明"为什么没排某些景点"。

### refine 联动（守住 M6 不变量）
- `refine.py` 的 `_rebuild_transport` 不变。
- `add` / `replace` 时新景点补 `visit_minutes`（调同一 enrich 工具），对受影响天跑预算复校，避免改完又超载。
- `relax`（太赶/轻松一点）接上新能力：调高 `DAY_BUDGET` 或减少当天景点数重排。

### 验证（测试）
- 纯函数单测：`day_used_minutes`、`transit_minutes`、预选闸门、预算复校再平衡、两条降级路径（sklearn 缺失→方位角回退、Tavily 缺失→静态表）。
- 不变量测试：每对相邻停靠点恰好一个 transport 段（M6 守住）；每天 `day_used_minutes ≤ DAY_BUDGET`。
- 跑现有测试套件确保 Task7/M6 断言不回归。

### 安全
- Tavily key 走 config `SecretStr`，不下发前端、不进日志/SSE（沿用 amap key 约束）。

## 新增/改动文件清单

| 文件 | 改动 |
|---|---|
| `backend/app/tools/amap.py` | 加 `extensions=all`，解析 rating/cost/opentime |
| `backend/app/tools/web_search.py` | 新增 Tavily 工具 |
| `backend/app/graph/nodes/enrich_duration.py` | 新增时长富化节点（Tavily agent + 静态表降级） |
| `backend/app/graph/nodes/itinerary.py` | 替换 cluster_by_day → 预选+KMeans+预算复校；加时间预算函数 |
| `backend/app/graph/nodes/refine.py` | add/replace 补 visit_minutes + 预算复校；relax 调 DAY_BUDGET |
| `backend/app/graph/builder.py` | 插入 enrich_duration 节点 |
| `backend/app/graph/state.py` | 加 `dropped_attractions` 等字段 |
| `backend/app/core/config.py` | 加 `tavily_api_key` |
| `backend/pyproject.toml` | 加 `scikit-learn`、`langchain-tavily` 依赖 |
| `backend/tests/` | 新增上述单测 + 不变量测试 |
