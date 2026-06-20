# M6 设计：路线规划（行程地理质量 + 路线绘制）

- 日期：2026-06-20
- 里程碑：**M6（路线规划）**——由原"产品化预留：路线规划绘制"提为 MVP；原 M6（交互打磨与导出）顺延为 M7，原 M7（产品化）顺延为 M8
- 范围：**后端为主**——重写 `itinerary` 的结构生成，让算法主导「分天 + 顺路 + 就近餐厅 + 交通段」；前端只做最小适配
- 验收标准：同一城市行程里，每天餐厅贴着当天景点（不再折返市中心）、每对相邻点之间都有交通段、交通方式与距离匹配；前端总览路线连续、按天配色、无 7km 步行怪线

---

## 0. 问题与根因（已用真实数据验证）

从 `backend/data/checkpoints.sqlite` 解出的真实广州 3 天 `day_plans` 暴露出"乱七八糟"的根因，按视觉影响排序：

1. **餐厅全城检索、未按天就近分配**（最大元凶）：`restaurants` 只做 `search_poi(城市, "美食")` 全城搜索，每天餐厅都挤在市中心；郊区景点玩完折返市中心吃饭 → 巨大回环（Day3 景点在花都，餐厅在市中心，直线差 ~30km）。
2. **景点也是全城热门检索**，跨度极大（塱头古村/花都湖在花都区，离市区 40km），即使最优顺序也有超长腿。
3. **确定性"顺路"排序被丢弃**：`cluster_by_day()` 排好的顺序只是当参考喂给 LLM，最终 items 顺序由 LLM 自由生成（把市中心餐厅插在两个郊区景点之间）。
4. **交通段是 LLM 编的**：`transport` 节点空转；交通段坐标全 `(0,0)`、`from/to` 与实际相邻点对不上、`mode` 经常错（7km 标"步行"）、且稀疏（一天 5 点只有 1 段）。
5. **前端 `afee8c3` 回归**：总览从"一条带途经点的连续路线"改成"每段交通各画一条独立路线"，只在有交通段处画线 → 路径断裂；各段 mode 不同 → 怪线。

**结论**：不是地图画错了，是喂给地图的点本身顺序烂 + 餐厅离景点几十公里 + 交通段瞎编。根治必须在后端数据层。

---

## 决策摘要

| 决策点 | 选择 | 说明 |
|---|---|---|
| M6 范围 | 后端数据为主 | 根因在数据层；前端分段画法在数据修好后自动连成完整路线，只需校验微调 |
| 排序主导权 | **算法主导，LLM 只填软字段** | 算法定顺序/坐标/交通段/mode；LLM 只回填 `cost/note/indoor/start/end`，按 poi_id 合并、几何与顺序一律以算法为准 |
| 餐厅就近 | **按簇周边搜索** | 新增 `amap.search_around`（高德 `place/around`），围绕每天簇中心搜餐厅；算法把每顿饭分给离当前位置最近的候选 |
| 交通段 | **后端出干净分段，前端画线** | 算法在每对相邻点间插 `transport`：真实起讫坐标（沿用相邻点）+ 真实 from/to 名 + 按直线距离定 mode；后端不调路径 API（省延迟/配额），前端用现有 JS SDK 画线并取距离时长 |
| 交通方式阈值 | 直线距离分档 | `<1km 步行` / `1–5km 公交`（含地铁）/ `>5km 驾车`；阈值收在 `constants.py` 便于调 |
| 酒店连线 | M6 不强连 | 交通段只在「停靠点之间」插入，首尾不接酒店 → 跨天酒店腿不再产生，总览自动变干净；酒店仍打点。stop↔hotel 连线列为 M7 可选增强 |

---

## 1. 架构与数据流变化

**图结构不变**（仍是 `clarify → dispatch → retrieve → [weather/attractions/restaurants/transport 并行] → itinerary → accommodation → budget → summarize`）。改动集中在节点内部：

```
attractions(全城景点池) ┐
restaurants(全城兜底池) ┼─→ itinerary ★重写
weather               ┘      │
                             ├ 1. cluster_by_day(景点) → 每天有序景点 + 簇中心（保留）
                             ├ 2. 每天 search_around(簇中心,"美食") → 当天就近餐厅池
                             ├ 3. build_day_stops(): 顺路插午/晚餐(就近) → 停靠点序列
                             ├ 4. insert_transport(): 每对相邻停靠点间插交通段(坐标/from/to/mode)
                             └ 5. LLM 软填(cost/note/indoor/time)，按 poi_id 合并，顺序坐标不动
```

- **职责收口**：`itinerary` 从"调一次 LLM 出整张行程"变为"算法搭骨架 + LLM 填血肉"。
- **`restaurants` 节点降级为兜底**：仍产出全城餐厅池，但只在某天 `search_around` 返回空时兜底使用。
- **`transport` 节点**：不再负责段生成（本就空转），保持返回 `{}`，不从图里删（避免动拓扑），留 M7 清理。

---

## 2. 组件设计

### 2.1 新增工具 `amap.search_around()` — `app/tools/amap.py`

```python
@traceable(run_type="tool", name="amap_search_around")
async def search_around(lng: float, lat: float, keywords: str,
                        poi_type: str = "", radius: int = 3000,
                        page_size: int = 20) -> list[dict]:
    """围绕坐标的周边检索（高德 place/around）。返回结构同 search_poi。失败/空 []。"""
    # GET {_BASE}/place/around  params: key, location="lng,lat", keywords, types, radius, offset, sortrule=distance
    # 解析同 search_poi：name/poi_id/lng/lat/address/type
```

- 与现有 `search_poi` 同构（同样的容错降级、同样的输出字段），便于复用解析。
- `sortrule=distance` 让高德按距离排序，配合算法"就近挑"。

### 2.2 重写 `itinerary` 节点 — `app/graph/nodes/itinerary.py`

**保留**：`cluster_by_day()`、`_nearest_neighbor_order()`、`_dist()`（已是正确的顺路逻辑）。

**新增纯函数（可单测，零 I/O）**：

```python
def haversine_km(a: dict, b: dict) -> float:
    """两点直线距离(km)。用于定 mode 与就近挑选。"""

def mode_by_distance(km: float) -> str:
    """<WALK_KM 步行 / <TRANSIT_KM 公交 / 否则 驾车。阈值取自 constants。"""

def pick_nearest(pool: list[dict], anchor: dict, used: set[str]) -> dict | None:
    """从 pool 里挑离 anchor 最近且未用过的一个（按 poi_id 去重）。"""

def build_day_stops(attractions_ordered: list[dict], rest_pool: list[dict]) -> list[dict]:
    """顺路停靠点序列：遍历有序景点，在午餐位(过半)、晚餐位(末尾)插入离当前位置最近的餐厅。
    返回 [{type:'attraction'|'meal', name, poi_id, location, ...}]，无交通、无软字段。"""

def insert_transport(stops: list[dict]) -> list[dict]:
    """每对相邻停靠点 (p, q) 间插一个 transport：
       {type:'transport', from:p.name, to:q.name, location:p.location,
        mode:mode_by_distance(haversine_km(p,q))}。返回交错后的完整 items。"""
```

**异步节点流程**：

```python
async def itinerary(state, config) -> dict:
    days = state.get("days", 3) or 3
    clusters = cluster_by_day(state.get("attractions", []) or [], days)
    daily_centers = [centroid(c) for c in clusters]
    food_kw = (state.get("preferences") or {}).get("food") or "美食"

    raw_days = []
    for d, cluster in enumerate(clusters, start=1):
        center = daily_centers[d-1]
        pool = await amap.search_around(center["lng"], center["lat"], food_kw, "餐饮") \
               or city_restaurant_fallback(state)        # 兜底
        stops = build_day_stops(cluster, pool)
        items = insert_transport(stops)
        raw_days.append({"day": d, "items": items, "center": center})

    # LLM 只填软字段：传入固定 items（名称/类型/坐标/顺序），回填 cost/note/indoor/start/end
    annotated = await annotate_soft_fields(raw_days, state, config)  # 按 poi_id 合并，顺序坐标不动

    return {
        "daily_centers": daily_centers,
        "day_plans": annotated,
        "plan_version": (state.get("plan_version", 0) or 0) + 1,
        "changed_days": [d["day"] for d in annotated],
    }
```

**软填合并约束（关键）**：`annotate_soft_fields` 把算法排好的 items 交 LLM，要求"只补 `cost/note/indoor/start/end`，**严禁改名/改坐标/改顺序/增删项**"；返回后算法**只取软字段、按 poi_id（交通段按索引）覆盖回原 items**，LLM 即便乱动也被丢弃。交通段 `cost` 由 mode 简单估（步行 0 / 公交小额 / 驾车按 km），不进 LLM，保证 budget 汇总不破。

### 2.3 阈值常量 — `app/core/constants.py`

```python
WALK_KM = 1.0          # <1km 步行
TRANSIT_KM = 5.0       # 1~5km 公交/地铁；>5km 驾车
AROUND_RADIUS_M = 3000 # 周边餐厅搜索半径
```

### 2.4 前端最小适配 — `frontend/src/composables/useAMap.ts` / `MapView.vue`

- **mode 字符串契约（关键）**：`mode_by_distance` 必须返回前端选插件用的关键字——`"步行"`（→ `AMap.Walking`）/ `"公交"`（→ `AMap.Transfer`，前端按 `includes('公交')||includes('地铁')` 命中）/ `"驾车"`（→ `AMap.Driving`）。三档与前端 `drawRoute`/`drawOverviewRoute` 现有判断一一对应，改了任一边都要同步。
- **预期零/极小改动**：后端保证"每对相邻停靠点都有交通段 + mode 合理"后，现有分段 `drawOverviewRoute` 会自动连成完整路线，7km 步行怪线消失。
- 交通段不再首尾接酒店 → `getTransportNeighbors` 不再产生跨天酒店腿 → 总览自动变干净。
- 按天配色已有，无需动。
- 仅需**校验**：总览/按天/选中段三种状态显示正确；如分段间有缝隙再做微调。

---

## 3. 测试

**确定性纯函数单测**（不依赖高德/LLM）：
- `haversine_km`：已知两点距离误差范围内。
- `mode_by_distance`：边界值（0.9/1.0/4.9/5.0/5.1km）落档正确。
- `pick_nearest`：就近选中、`used` 去重、空池返回 None。
- `build_day_stops`：午/晚餐插在正确位置、餐厅取自就近、顺序为景点顺路序。
- `insert_transport`：N 个停靠点 → N-1 段；每段 from/to/坐标/mode 正确。
- `cluster_by_day`（回归）：保持原有顺路行为不变。

**集成/回归**：用截图那次广州 case（mock `search_around` 返回各簇周边餐厅）跑 `itinerary`，断言：① 每天餐厅离当天簇中心 < 阈值；② 无"相邻停靠点直线距离 > 全天最大景点跨度"的折返；③ 每对相邻点有且仅有一段交通；④ 交通段 mode 与距离一致。

**手动验收**：真实跑一次广州 3 天，前端总览路线连续、餐厅贴景点、无怪线。

---

## 4. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| `search_around` 周边无好餐厅（偏远景点） | 当天餐厅仍远 | 半径递增重试一次 → 仍空则全城池兜底；记日志 |
| 每天多 1~2 次高德请求 | 配额/延迟 | 仅按天一次（用簇中心，非逐点）；高德 `search_poi` 已有 5s 超时与降级 |
| LLM 软填时擅自改序/改坐标 | 几何被污染 | 合并层只取软字段、按 poi_id 覆盖，结构性字段一律丢弃 LLM 输出 |
| 午/晚餐启发式不贴合（如单景点日） | 餐厅位置生硬 | MVP 用"过半插午餐、末尾插晚餐"；景点数 <2 时只插一顿；列为可调 |
| 前端实际仍需改动 | 范围外溢 | 校验阶段若发现分段缝隙，限定在 `drawOverviewRoute` 内微调，不重写 |

---

## 5. 里程碑重排（同步进 `项目策划书.md`）

| 新编号 | 内容 | 来源 |
|---|---|---|
| **M6** | **路线规划（行程地理质量 + 路线绘制）** | 本方案（原在 M7 产品化预留的"路线规划绘制"） |
| M7 | 交互打磨与导出 | ← 原 M6 |
| M8 | 产品化预留（用户系统、PG/Redis、容器化、限流监控） | ← 原 M7 |

策划书同步改动：① 1.3 范围表"地图联动"行——"路线规划绘制"从产品化列移到 MVP 列；② 2.3 功能清单——新增"逐日顺路路线规划与地图绘制（就近餐饮 + 分段交通）"；③ 第八章里程碑——M6/M7/M8 重写。
