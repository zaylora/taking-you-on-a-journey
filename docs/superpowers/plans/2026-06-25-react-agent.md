# ReAct Agent 重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把后端 16 节点固定编排图重构为单一 ReAct Agent（`create_agent`）+ 一组确定性 tools，由 LLM 自主决策；删除全部外围节点与死代码。

**Architecture:** `build_graph(checkpointer)` 直接返回 `create_agent(model, tools, system_prompt, state_schema, checkpointer)`，无任何外层包裹节点。确定性业务规则（费用核算、分天聚类、过夜判定、changed_days diff）抽成纯函数模块，由对应 tool 内部调用；LLM 只决定调哪个 tool/几次/何时收尾。`ask_user` 经 `interrupt()` 自主澄清；`finalize_plan` 经 `Command` 写 state 并自动 diff 出 changed_days。最终回复（含中间思考文本）由 agent 本体流式输出。

**Tech Stack:** Python 3.12 / FastAPI / LangChain 1.3.9 / LangGraph 1.2.5 (`langchain.agents.create_agent`) / pytest + pytest-asyncio / uv。

## Global Constraints

- 依赖优先原则（CLAUDE.md）：优先成熟开源依赖，不盲目手写。本计划复用 `create_agent`、`amap.py`、既有纯函数。
- 运行命令：`uv run pytest ...`（项目用 uv 管理，`.venv` 由 uv 自建）。
- LangGraph 版本：`langgraph==1.2.5` / `langchain>=1.3.9`；`create_agent` 来自 `from langchain.agents import create_agent`（已验证）。
- `create_agent` 参数名是 **`system_prompt`**（非 `prompt`）；自定义 state 继承 `from langchain.agents import AgentState`。
- tool 读 state：`InjectedState`（`from langgraph.prebuilt import InjectedState`）；写 state：返回 `Command(update={...})`（`from langgraph.types import Command`）+ `InjectedToolCallId`（`from langchain_core.tools import InjectedToolCallId`）。
- 业务口径不变（M4）：cost 为人均、hotel.price 为每晚整间价；`estimated = num_people × Σ(人均项) + Σ(hotel.price)`；`limit==0` 表示不限；`_MAX_RETRY=2`。
- 过夜日 = 除最后一天外每天；单日游无住宿。
- SSE 事件契约不变：`EVENT_CLARIFY` / `EVENT_TOKEN` / `EVENT_PLAN_PATCH` / `EVENT_FINAL` 语义与 data 结构保留。
- 测试不依赖真实 Key/网络：用 `tests/conftest.py` 的 `fake_amap` fixture + 可 `bind_tools` 的脚本化假模型。
- 测试惯例：纯函数测试直接 import 被测函数；assert 具体值（见 `tests/test_budget.py`）。
- 删除死代码前对每个符号全仓 `grep` 确认无残余引用，删除后跑全量测试绿。

---

## 文件结构（决策锁定）

新增模块（确定性纯函数 + 工具 + agent 装配）：

- `app/agent/__init__.py` — 包标记
- `app/agent/state.py` — `TripState(AgentState)`：业务字段
- `app/agent/planning.py` — 迁入的纯函数：`cluster_by_day` / `_nearest_neighbor_order` / `_dist` / `daily_centers_of` + itinerary 的 Pydantic schema（`Location/DayWeather/PlanItem/Hotel/DayPlan/DayPlans`）+ 编排 `_SYS`
- `app/agent/budgeting.py` — 迁入：`compute_budget` / `_sum_costs` / `_pick_cut_suggestions` / `_MAX_RETRY`
- `app/agent/lodging.py` — 迁入：`overnight_days` / `attach_hotels` / `hotel_keyword` + 住宿 schema（`_HotelForDay/_AccoResult`）+ 住宿 `_SYS`
- `app/agent/diffing.py` — 新增：`diff_changed_days(old, new) -> list[int]`
- `app/agent/tools.py` — 9 个 `@tool`：检索 4 + 编排 2 + 核算 1 + ask_user + finalize_plan
- `app/agent/prompt.py` — `TRIP_AGENT_SYS` 系统提示
- `app/agent/build.py` — `build_trip_agent(checkpointer)` = `create_agent(...)`

改写：

- `app/graph/builder.py` — `build_graph` 改为转调 `build_trip_agent`
- `app/graph/stream.py` — token 放行改为放行所有 `on_chat_model_stream` 文本；`summary` 取末条 AIMessage
- `app/core/constants.py` — 精简 `NODES`/`NODE_LABELS`；删 `MAX_CLARIFY_ROUNDS`
- `app/llm/factory.py` — 支持 `disable_streaming=False` 透传（已支持 `**overrides`，验证即可）

删除（见 Task 12）：`app/graph/nodes/` 下全部节点文件 + 旧测试。

测试（新增）：

- `tests/agent/test_diffing.py` / `test_planning.py` / `test_budgeting.py` / `test_lodging.py` / `test_tools.py` / `test_build_agent.py` / `test_stream_react.py`

---

## Task 1: 确定性纯函数模块 `diffing.py`（changed_days diff）

**Files:**
- Create: `app/agent/__init__.py`
- Create: `app/agent/diffing.py`
- Test: `tests/agent/__init__.py`, `tests/agent/test_diffing.py`

**Interfaces:**
- Produces: `diff_changed_days(old: list[dict], new: list[dict]) -> list[int]` — 比对新旧 day_plans 每天的 items 指纹（`type|name|poi_id` 序列）+ hotel 指纹（`name|poi_id`），返回有变化的 `day` 号升序列表。新增天/删除天也算变化。

- [ ] **Step 1: 写失败测试**

Create `tests/agent/__init__.py`（空文件）。

Create `tests/agent/test_diffing.py`:

```python
from app.agent.diffing import diff_changed_days


def _day(day, items, hotel=None):
    d = {"day": day, "items": items}
    if hotel is not None:
        d["hotel"] = hotel
    return d


def _it(type_, name, poi_id=""):
    return {"type": type_, "name": name, "poi_id": poi_id}


def test_no_change_returns_empty():
    a = [_day(1, [_it("attraction", "故宫", "p1")])]
    assert diff_changed_days(a, a) == []


def test_full_replan_all_days_changed():
    old = []
    new = [_day(1, [_it("attraction", "A")]), _day(2, [_it("attraction", "B")])]
    assert diff_changed_days(old, new) == [1, 2]


def test_single_day_item_change():
    old = [_day(1, [_it("attraction", "A", "p1")]), _day(2, [_it("attraction", "B", "p2")])]
    new = [_day(1, [_it("attraction", "A", "p1")]), _day(2, [_it("attraction", "C", "p3")])]
    assert diff_changed_days(old, new) == [2]


def test_hotel_change_marks_day():
    old = [_day(1, [_it("attraction", "A")], hotel={"name": "H1", "poi_id": "h1"})]
    new = [_day(1, [_it("attraction", "A")], hotel={"name": "H2", "poi_id": "h2"})]
    assert diff_changed_days(old, new) == [1]


def test_removed_day_marked():
    old = [_day(1, [_it("attraction", "A")]), _day(2, [_it("attraction", "B")])]
    new = [_day(1, [_it("attraction", "A")])]
    assert diff_changed_days(old, new) == [2]
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/agent/test_diffing.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.agent.diffing'`

- [ ] **Step 3: 写最小实现**

Create `app/agent/__init__.py`（空文件）。

Create `app/agent/diffing.py`:

```python
"""changed_days 增量 diff：比对新旧 day_plans，确定性纯函数。

供 finalize_plan tool 在写入 day_plans 时计算前端增量重绘所需的 changed_days。
"""


def _item_fp(item: dict) -> str:
    return f"{item.get('type', '')}|{item.get('name', '')}|{item.get('poi_id', '')}"


def _hotel_fp(hotel: dict | None) -> str:
    if not hotel:
        return ""
    return f"{hotel.get('name', '')}|{hotel.get('poi_id', '')}"


def _day_fp(day_plan: dict) -> str:
    items = day_plan.get("items", []) or []
    items_fp = ";".join(_item_fp(it) for it in items)
    return f"{items_fp}#{_hotel_fp(day_plan.get('hotel'))}"


def diff_changed_days(old: list[dict], new: list[dict]) -> list[int]:
    """返回有变化的 day 号（升序）。新增/删除天也算变化。"""
    old_by_day = {d.get("day"): _day_fp(d) for d in (old or [])}
    new_by_day = {d.get("day"): _day_fp(d) for d in (new or [])}
    changed: set[int] = set()
    for day in set(old_by_day) | set(new_by_day):
        if old_by_day.get(day) != new_by_day.get(day):
            if day is not None:
                changed.add(day)
    return sorted(changed)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/agent/test_diffing.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add app/agent/__init__.py app/agent/diffing.py tests/agent/__init__.py tests/agent/test_diffing.py
git commit -m "feat(react): diff_changed_days 纯函数 + 单测"
```

---

## Task 2: 迁移规划纯函数与 schema 到 `planning.py`

把 `itinerary.py` 的纯函数与 Pydantic schema 原样迁入新模块（不改算法），让工具层依赖新模块、为后续删除旧节点铺路。

**Files:**
- Create: `app/agent/planning.py`
- Test: `tests/agent/test_planning.py`

**Interfaces:**
- Consumes: 无（自包含）
- Produces:
  - `cluster_by_day(points: list[dict], days: int) -> list[list[dict]]`（贪心顺路分天，算法与 `itinerary.cluster_by_day` 逐字节一致）
  - `daily_centers_of(clusters: list[list[dict]]) -> list[dict]` — 每簇质心 `{lng,lat}`（提炼自 itinerary 节点内联逻辑）
  - Pydantic schema：`Location` / `DayWeather` / `PlanItem` / `Hotel` / `DayPlan` / `DayPlans`
  - `ITINERARY_SYS: str` — 编排系统提示

- [ ] **Step 1: 写失败测试**

Create `tests/agent/test_planning.py`:

```python
from app.agent.planning import cluster_by_day, daily_centers_of, DayPlans, PlanItem


def _p(name, lng, lat):
    return {"name": name, "lng": lng, "lat": lat}


def test_cluster_empty_returns_empty_buckets():
    assert cluster_by_day([], 3) == [[], [], []]


def test_cluster_balances_points_across_days():
    pts = [_p(str(i), 104.0 + i * 0.01, 30.6 + i * 0.01) for i in range(6)]
    buckets = cluster_by_day(pts, 3)
    assert len(buckets) == 3
    assert sum(len(b) for b in buckets) == 6
    # 均衡：每天 2 个
    assert all(len(b) == 2 for b in buckets)


def test_daily_centers_centroid():
    clusters = [[_p("a", 100.0, 30.0), _p("b", 102.0, 32.0)], []]
    centers = daily_centers_of(clusters)
    assert centers[0] == {"lng": 101.0, "lat": 31.0}
    assert centers[1] == {"lng": 0.0, "lat": 0.0}


def test_dayplans_schema_parses():
    dp = DayPlans(days=[{"day": 1, "items": [{"type": "attraction", "name": "故宫"}]}])
    assert dp.days[0].day == 1
    assert dp.days[0].items[0].name == "故宫"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/agent/test_planning.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.agent.planning'`

- [ ] **Step 3: 写实现（迁移 itinerary.py 的纯函数 + schema）**

Create `app/agent/planning.py`，从 `app/graph/nodes/itinerary.py` 复制以下内容（**保持算法逐字节一致**）：

```python
"""行程规划纯函数与结构化 schema（迁自 itinerary 节点，算法不变）。

cluster_by_day：贪心顺路分天；daily_centers_of：每簇质心。
schema：供 assemble_itinerary tool 的 LLM structured output 使用。
"""
import math

from pydantic import BaseModel, Field


# ---- Pydantic schemas（迁自 itinerary.py）----

class Location(BaseModel):
    lng: float = Field(default=0.0, description="经度，沿用输入坐标，不要自行编造")
    lat: float = Field(default=0.0, description="纬度，沿用输入坐标，不要自行编造")


class DayWeather(BaseModel):
    text: str = Field(default="", description="天气描述，如“晴”“小雨”；沿用输入天气数据")
    temp: str = Field(default="", description="气温，如“18~26℃”；沿用输入天气数据")
    is_rainy: bool = Field(default=False, description="当天是否下雨，下雨时应优先安排室内项")


class PlanItem(BaseModel):
    type: str = Field(description="行程项类型，仅限三种：attraction（景点）、meal（餐饮）、transport（交通）")
    name: str = Field(default="", description="景点或餐厅名称；transport 项可留空")
    poi_id: str = Field(default="", description="高德 POI id，沿用输入数据，不要编造")
    location: Location = Field(default_factory=Location, description="该项经纬度，沿用输入坐标")
    start: str = Field(default="", description="开始时间，24 小时制 HH:MM，如 09:30")
    end: str = Field(default="", description="结束时间，24 小时制 HH:MM，如 11:30")
    indoor: bool = Field(default=False, description="是否室内项；雨天优先安排 indoor=true 的项")
    note: str = Field(default="", description="补充说明，一句话简述安排理由或注意事项")
    mode: str = Field(default="", description="交通方式，如“步行”“地铁”“驾车”；仅 transport 项填写")
    from_: str = Field(default="", alias="from", description="交通出发地名称；仅 transport 项填写")
    to: str = Field(default="", description="交通目的地名称；仅 transport 项填写")
    cost: float = Field(default=0.0, description="该项人均花费(元)：门票/餐标/市内交通；免费景点或交通项填 0")

    model_config = {"populate_by_name": True}


class Hotel(BaseModel):
    name: str = Field(default="", description="酒店名称，沿用候选池，不要编造")
    poi_id: str = Field(default="", description="高德 POI id；降级参考酒店可留空")
    location: Location = Field(default_factory=Location, description="酒店经纬度")
    price: float = Field(default=0.0, description="每晚整间价(元)，按住宿档位估")
    level: str = Field(default="", description="住宿档位：经济/舒适/高端")


class DayPlan(BaseModel):
    day: int = Field(description="第几天，从 1 开始的正整数")
    date: str = Field(default="", description="当天日期，格式 YYYY-MM-DD；由 start_date 顺延推算")
    weather: DayWeather = Field(default_factory=DayWeather, description="当天天气，沿用输入天气数据")
    center: Location = Field(default_factory=Location, description="当天活动的中心坐标")
    items: list[PlanItem] = Field(default_factory=list, description="当天按时间顺序排列的行程项")
    hotel: Hotel | None = Field(default=None, description="当晚住宿；离程日/单日游为 None")


class DayPlans(BaseModel):
    days: list[DayPlan] = Field(default_factory=list, description="逐天行程，长度应等于总天数")


ITINERARY_SYS = (
    "你是行程编排助手。给定每天的景点簇、餐厅候选、交通与天气，为每天安排合理的时间线："
    "上午/下午景点、午餐/晚餐就近分配餐厅、必要的市内交通。雨天优先室内项。"
    "为每个行程项估算人均花费 cost（元）：门票按景点合理价、餐标按餐厅档位、市内交通按方式估；"
    "免费景点或无费用项填 0。"
    "若输入含 budget_advice（上轮超支额与削减建议），据此压低总花费："
    "优先减少或替换高价付费景点、降低餐标、精简交通。"
    "输出严格符合给定结构（含每项的 location 经纬度与 cost，沿用输入坐标）。"
)


# ---- 纯函数（迁自 itinerary.py，算法不变）----

def _dist(a: dict, b: dict) -> float:
    return math.hypot(a.get("lng", 0.0) - b.get("lng", 0.0),
                      a.get("lat", 0.0) - b.get("lat", 0.0))


def _nearest_neighbor_order(seg: list[dict]) -> list[dict]:
    if not seg:
        return []
    remaining = list(seg)
    cur = min(remaining, key=lambda p: (p.get("lng", 0.0), p.get("lat", 0.0)))
    remaining.remove(cur)
    route = [cur]
    while remaining:
        nxt = min(remaining, key=lambda p: _dist(p, route[-1]))
        remaining.remove(nxt)
        route.append(nxt)
    return route


def cluster_by_day(points: list[dict], days: int) -> list[list[dict]]:
    """贪心：按方位角排序 → 均衡切 days 段 → 段内最近邻顺路。纯函数。"""
    days = max(1, days)
    buckets: list[list[dict]] = [[] for _ in range(days)]
    if not points:
        return buckets
    cx = sum(p.get("lng", 0.0) for p in points) / len(points)
    cy = sum(p.get("lat", 0.0) for p in points) / len(points)
    ordered = sorted(points, key=lambda p: math.atan2(p.get("lat", 0.0) - cy,
                                                       p.get("lng", 0.0) - cx))
    n = len(ordered)
    base, extra = divmod(n, days)
    idx = 0
    for d in range(days):
        size = base + (1 if d < extra else 0)
        seg = ordered[idx:idx + size]
        idx += size
        buckets[d] = _nearest_neighbor_order(seg)
    return buckets


def daily_centers_of(clusters: list[list[dict]]) -> list[dict]:
    """每簇质心 {lng,lat}；空簇 {0,0}。纯函数。"""
    centers = []
    for c in clusters:
        if c:
            cx = sum(p.get("lng", 0.0) for p in c) / len(c)
            cy = sum(p.get("lat", 0.0) for p in c) / len(c)
        else:
            cx = cy = 0.0
        centers.append({"lng": cx, "lat": cy})
    return centers
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/agent/test_planning.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add app/agent/planning.py tests/agent/test_planning.py
git commit -m "feat(react): 迁移规划纯函数+schema 到 agent/planning"
```

---

## Task 3: 迁移预算纯函数到 `budgeting.py`

**Files:**
- Create: `app/agent/budgeting.py`
- Test: `tests/agent/test_budgeting.py`

**Interfaces:**
- Produces: `compute_budget(day_plans, num_people, limit, retry_count) -> dict`（返回 `{"budget_check","advice","retry_count"}`，口径与 `budget.compute_budget` 一致）；`_sum_costs` / `_pick_cut_suggestions` / `_MAX_RETRY`。

- [ ] **Step 1: 写失败测试**

Create `tests/agent/test_budgeting.py`:

```python
from app.agent.budgeting import compute_budget, _sum_costs


def _day(day, items, hotel=None):
    d = {"day": day, "items": items}
    if hotel is not None:
        d["hotel"] = hotel
    return d


def _item(type_, name, cost):
    return {"type": type_, "name": name, "cost": cost}


def test_sum_costs_per_person_and_whole_room():
    dps = [_day(1, [_item("attraction", "A", 100), _item("meal", "M", 50)], hotel={"price": 400}),
           _day(2, [_item("attraction", "B", 80)])]
    s = _sum_costs(dps, num_people=2)
    # 过夜日=第1天；hotel 整间不乘人数；人均项乘 2
    assert s["breakdown"] == {"ticket": (100 + 80) * 2, "food": 50 * 2, "transport": 0, "hotel": 400}
    assert s["estimated"] == (100 + 80) * 2 + 50 * 2 + 400


def test_over_budget_retry_then_advice():
    dps = [_day(1, [_item("attraction", "A", 800), _item("meal", "M", 300)], hotel={"price": 1000}),
           _day(2, [])]
    res = compute_budget(dps, num_people=1, limit=1000, retry_count=0)
    assert res["budget_check"]["over"] is True
    assert res["budget_check"]["retry"] is True
    assert res["retry_count"] == 1
    assert res["advice"]["over_amount"] > 0


def test_retry_capped_at_max():
    dps = [_day(1, [_item("attraction", "A", 5000)], hotel={"price": 1}), _day(2, [])]
    res = compute_budget(dps, num_people=1, limit=100, retry_count=2)
    assert res["budget_check"]["over"] is True
    assert res["budget_check"]["retry"] is False  # retry_count 已达 _MAX_RETRY
    assert "已尽力压缩" in res["budget_check"]["note"]
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/agent/test_budgeting.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写实现（从 budget.py 复制 compute_budget/_sum_costs/_pick_cut_suggestions/_MAX_RETRY，去掉图节点 budget()/route_after_budget()）**

Create `app/agent/budgeting.py`:

```python
"""预算核算纯函数（迁自 budget 节点）。口径：cost 人均、hotel.price 整间；limit==0 不限。"""

_MAX_RETRY = 2


def _sum_costs(day_plans: list, num_people: int) -> dict:
    ticket = food = transport = hotel = 0.0
    days_list = sorted(d.get("day", 0) for d in day_plans)
    overnight = set(days_list[:-1]) if len(days_list) > 1 else set()
    for d in day_plans:
        for it in d.get("items", []) or []:
            c = it.get("cost", 0.0) or 0.0
            t = it.get("type", "")
            if t == "attraction":
                ticket += c
            elif t == "meal":
                food += c
            elif t == "transport":
                transport += c
        h = d.get("hotel")
        if h and d.get("day", 0) in overnight:
            hotel += h.get("price", 0.0) or 0.0
    n = max(1, num_people)
    breakdown = {
        "ticket": round(ticket * n, 2),
        "food": round(food * n, 2),
        "transport": round(transport * n, 2),
        "hotel": round(hotel, 2),
    }
    estimated = round(breakdown["ticket"] + breakdown["food"]
                      + breakdown["transport"] + breakdown["hotel"], 2)
    return {"breakdown": breakdown, "estimated": estimated}


def _pick_cut_suggestions(day_plans: list, top: int = 3) -> list:
    items = []
    for d in day_plans:
        for it in d.get("items", []) or []:
            cost = it.get("cost", 0.0) or 0.0
            if it.get("type", "") in ("attraction", "meal") and cost > 0:
                items.append({"day": d.get("day", 0), "type": it.get("type", ""),
                              "name": it.get("name", ""), "cost": round(cost, 2)})
    items.sort(key=lambda x: (-x["cost"], x["day"], x["name"]))
    return items[:top]


def compute_budget(day_plans: list, num_people: int, limit: float, retry_count: int) -> dict:
    """核心纯函数：产出 budget_check、advice(None|dict)、new_retry_count。"""
    sums = _sum_costs(day_plans, num_people)
    estimated = sums["estimated"]
    over = limit > 0 and estimated > limit
    retry = over and retry_count < _MAX_RETRY
    new_count = retry_count + (1 if retry else 0)
    note = ""
    if over and not retry:
        note = f"已尽力压缩，仍超出预算约 ¥{round(estimated - limit)}"
    budget_check = {
        "limit": round(limit, 2), "estimated": estimated, "over": over, "retry": retry,
        "breakdown": sums["breakdown"], "retry_count": new_count, "note": note,
    }
    advice = None
    if retry:
        advice = {"over_amount": round(estimated - limit, 2),
                  "cut_suggestions": _pick_cut_suggestions(day_plans)}
    return {"budget_check": budget_check, "advice": advice, "retry_count": new_count}
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/agent/test_budgeting.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add app/agent/budgeting.py tests/agent/test_budgeting.py
git commit -m "feat(react): 迁移预算纯函数到 agent/budgeting"
```

---

## Task 4: 迁移住宿纯函数与 schema 到 `lodging.py`

**Files:**
- Create: `app/agent/lodging.py`
- Test: `tests/agent/test_lodging.py`

**Interfaces:**
- Produces: `overnight_days(day_plans) -> list[int]`；`attach_hotels(day_plans, assignments) -> list`；`hotel_keyword(level) -> str`；`ACCO_SYS: str`；schema `_HotelForDay` / `_AccoResult`（从 lodging 内部用，import planning.Hotel）。

- [ ] **Step 1: 写失败测试**

Create `tests/agent/test_lodging.py`:

```python
from app.agent.lodging import overnight_days, attach_hotels, hotel_keyword


def test_overnight_days_excludes_last():
    dps = [{"day": 1, "items": []}, {"day": 2, "items": []}, {"day": 3, "items": []}]
    assert overnight_days(dps) == [1, 2]


def test_overnight_single_day_none():
    assert overnight_days([{"day": 1, "items": []}]) == []


def test_attach_hotels_embeds_by_day():
    dps = [{"day": 1, "items": []}, {"day": 2, "items": []}]
    out = attach_hotels(dps, [{"day": 1, "hotel": {"name": "H1"}}])
    assert out[0]["hotel"] == {"name": "H1"}
    assert "hotel" not in out[1] or out[1].get("hotel") is None
    # 不改原对象
    assert "hotel" not in dps[0]


def test_hotel_keyword_maps_level():
    assert hotel_keyword("经济") == "经济型酒店"
    assert hotel_keyword("未知档") == "酒店"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/agent/test_lodging.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写实现（从 accommodation.py 迁移纯函数 + schema，schema 的 Hotel 改 import 自 planning）**

Create `app/agent/lodging.py`:

```python
"""住宿纯函数与 schema（迁自 accommodation 节点）。过夜日=除最后一天。"""
from pydantic import BaseModel, Field

from app.agent.planning import Hotel

_LEVEL_KEYWORD = {"经济": "经济型酒店", "舒适": "舒适型酒店", "高端": "高档酒店"}

ACCO_SYS = (
    "你是住宿规划助手。给定每个过夜日的活动中心坐标、住宿档位与酒店候选池，"
    "为每个过夜日就近选一家酒店，并按档位估每晚整间价 price（元）："
    "经济约 200~400、舒适约 400~800、高端约 800 以上。"
    "优先使用候选池中的真实酒店（带 poi_id 与坐标）；候选池为空时按档位与中心坐标给出参考酒店（poi_id 留空）。"
    "只为给定的过夜日分配，输出严格符合结构。"
)


class _HotelForDay(BaseModel):
    day: int = Field(description="过夜日序号（从 1 开始）")
    hotel: Hotel = Field(description="该晚住宿")


class _AccoResult(BaseModel):
    assignments: list[_HotelForDay] = Field(default_factory=list, description="逐过夜日的住宿分配")


def overnight_days(day_plans: list) -> list:
    """需住宿的天（除最后一天）。纯函数。"""
    days = sorted(d.get("day", 0) for d in day_plans)
    return days[:-1]


def hotel_keyword(level: str) -> str:
    return _LEVEL_KEYWORD.get(level, "酒店")


def attach_hotels(day_plans: list, assignments: list) -> list:
    """把 assignments（[{day, hotel}]）嵌入对应天，返回新 day_plans。不改原对象。"""
    by_day = {a["day"]: a["hotel"] for a in assignments}
    out = []
    for d in day_plans:
        dd = dict(d)
        if d.get("day") in by_day:
            dd["hotel"] = by_day[d["day"]]
        out.append(dd)
    return out
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/agent/test_lodging.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add app/agent/lodging.py tests/agent/test_lodging.py
git commit -m "feat(react): 迁移住宿纯函数+schema 到 agent/lodging"
```

---

## Task 5: Agent State 定义 `state.py`

**Files:**
- Create: `app/agent/state.py`
- Test: `tests/agent/test_state.py`

**Interfaces:**
- Produces: `TripState(AgentState)` — 含 `day_plans: list` / `changed_days: list` / `plan_version: int` / `budget_check: dict` / `retry_count: int` / `summary: str`（业务字段，供 tool 经 Command 写、InjectedState 读、stream 读出）。

- [ ] **Step 1: 写失败测试**

Create `tests/agent/test_state.py`:

```python
from app.agent.state import TripState


def test_tripstate_has_business_fields():
    ann = TripState.__annotations__
    for field in ("day_plans", "changed_days", "plan_version", "budget_check", "retry_count", "summary"):
        assert field in ann, f"缺业务字段 {field}"


def test_tripstate_inherits_messages():
    # AgentState 提供 messages；继承后应可见（在 MRO 注解里）
    all_ann = {}
    for klass in TripState.__mro__:
        all_ann.update(getattr(klass, "__annotations__", {}))
    assert "messages" in all_ann
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/agent/test_state.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写实现**

Create `app/agent/state.py`:

```python
"""ReAct Agent 状态：继承 create_agent 的 AgentState，叠加旅行业务字段。

业务字段由 tool 经 Command(update=...) 写、InjectedState 读，stream 层读出供 SSE。
messages 由 AgentState 提供（add_messages reducer），无需重复声明。
"""
from langchain.agents import AgentState


class TripState(AgentState):
    day_plans: list
    changed_days: list
    plan_version: int
    budget_check: dict
    retry_count: int
    summary: str
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/agent/test_state.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add app/agent/state.py tests/agent/test_state.py
git commit -m "feat(react): TripState 继承 AgentState 加业务字段"
```

---

## Task 6: 工具层 `tools.py` — 检索 4 工具

**Files:**
- Create: `app/agent/tools.py`
- Test: `tests/agent/test_tools.py`

**Interfaces:**
- Consumes: `app.tools.amap`（`search_poi/get_weather/plan_route`）
- Produces（本任务部分）：4 个 `@tool`：`search_attractions(city, keywords="热门景点")` / `search_restaurants(city, keywords="美食")` / `get_weather(city)` / `plan_route(origin, dest, mode="transit")`，各返回 dict/list（失败降级），均 `async`。工具用 `.ainvoke({...})` 调用，或 `.func`/底层取实现测试。

- [ ] **Step 1: 写失败测试**

Create `tests/agent/test_tools.py`:

```python
import pytest

from app.agent import tools


@pytest.mark.asyncio
async def test_search_attractions_returns_pois(fake_amap):
    fake_amap["search_poi"] = [{"name": "故宫", "poi_id": "p1", "lng": 116.4, "lat": 39.9}]
    out = await tools.search_attractions.ainvoke({"city": "北京", "keywords": "热门景点"})
    assert out[0]["name"] == "故宫"


@pytest.mark.asyncio
async def test_search_attractions_degrades_to_empty(fake_amap, monkeypatch):
    async def _boom(*a, **k): raise RuntimeError("amap down")
    monkeypatch.setattr("app.tools.amap.search_poi", _boom)
    out = await tools.search_attractions.ainvoke({"city": "北京", "keywords": "x"})
    assert out == []


@pytest.mark.asyncio
async def test_get_weather_tool(fake_amap):
    out = await tools.get_weather.ainvoke({"city": "成都"})
    assert out["text"] == "多云"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/agent/test_tools.py -v`
Expected: FAIL，`ModuleNotFoundError: app.agent.tools`

- [ ] **Step 3: 写实现（检索 4 工具）**

Create `app/agent/tools.py`:

```python
"""ReAct Agent 工具箱。每个 tool = LLM 可调接口 + 内部确定性实现。

检索类直接复用 app/tools/amap.py（失败降级，不抛）。
编排/核算/收尾类见后续步骤；ask_user 经 interrupt 暂停。
"""
from langchain_core.tools import tool

from app.tools import amap


@tool
async def search_attractions(city: str, keywords: str = "热门景点") -> list:
    """检索城市景点 POI。返回 [{name,poi_id,lng,lat,address,type}]；失败或无结果返回 []。"""
    try:
        return await amap.search_poi(city, keywords, "风景名胜")
    except Exception:  # noqa: BLE001 —— 降级，交 LLM 决策
        return []


@tool
async def search_restaurants(city: str, keywords: str = "美食") -> list:
    """检索城市餐饮 POI。返回 [{name,poi_id,lng,lat,...}]；失败或无结果返回 []。"""
    try:
        return await amap.search_poi(city, keywords, "餐饮")
    except Exception:  # noqa: BLE001
        return []


@tool
async def get_weather(city: str) -> dict:
    """查询城市天气。返回 {text,temp,is_rainy,source}；失败降级季节气候。"""
    try:
        return await amap.get_weather(city)
    except Exception:  # noqa: BLE001
        return {"text": "以当季气候为准", "temp": "", "is_rainy": False, "source": "climate"}


@tool
async def plan_route(origin: str, dest: str, mode: str = "transit") -> dict:
    """规划两地交通方案。返回高德 route dict；失败降级 {}。"""
    try:
        return await amap.plan_route(origin, dest, mode)
    except Exception:  # noqa: BLE001
        return {}
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/agent/test_tools.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add app/agent/tools.py tests/agent/test_tools.py
git commit -m "feat(react): 检索类 4 工具 + 降级单测"
```

---

## Task 7: 工具层 — 编排 2 工具（assemble_itinerary / assign_hotels）

这两个工具内部调 LLM（structured output）。`build_llm` 用 `app/llm/factory.build_llm`；测试时 monkeypatch 成 `FakeStructuredLLM`。

**Files:**
- Modify: `app/agent/tools.py`（追加）
- Test: `tests/agent/test_tools.py`（追加）

**Interfaces:**
- Consumes: `planning.cluster_by_day` / `daily_centers_of` / `DayPlans` / `ITINERARY_SYS`；`lodging.overnight_days` / `attach_hotels` / `hotel_keyword` / `_AccoResult` / `ACCO_SYS`；`app.llm.factory.build_llm`；`amap.search_poi`。
- Produces:
  - `assemble_itinerary(city, days, attractions, restaurants, weather, start_date="", num_people=1, budget_advice=None) -> dict` — 返回 `{"day_plans": [...], "daily_centers": [...]}`（day_plans 为 `by_alias` dump 的 list）。
  - `assign_hotels(city, day_plans, level="舒适", daily_centers=None) -> list` — 返回嵌入 hotel 的 day_plans。

- [ ] **Step 1: 写失败测试（追加到 test_tools.py）**

```python
from app.agent.planning import DayPlans
from app.agent.lodging import _AccoResult
from tests.conftest import make_fake_build_llm


@pytest.mark.asyncio
async def test_assemble_itinerary_builds_day_plans(fake_amap, monkeypatch):
    fake = DayPlans(days=[{"day": 1, "items": [{"type": "attraction", "name": "故宫", "cost": 60}]}])
    monkeypatch.setattr("app.agent.tools.build_llm", make_fake_build_llm(structured=fake))
    out = await tools.assemble_itinerary.ainvoke({
        "city": "北京", "days": 1,
        "attractions": [{"name": "故宫", "lng": 116.4, "lat": 39.9}],
        "restaurants": [], "weather": {"text": "晴"},
    })
    assert out["day_plans"][0]["day"] == 1
    assert out["day_plans"][0]["items"][0]["name"] == "故宫"
    assert "daily_centers" in out


@pytest.mark.asyncio
async def test_assign_hotels_embeds(fake_amap, monkeypatch):
    res = _AccoResult(assignments=[{"day": 1, "hotel": {"name": "如家", "price": 300, "level": "经济"}}])
    monkeypatch.setattr("app.agent.tools.build_llm", make_fake_build_llm(structured=res))
    dps = [{"day": 1, "items": []}, {"day": 2, "items": []}]  # 过夜日=第1天
    out = await tools.assign_hotels.ainvoke({"city": "北京", "day_plans": dps, "level": "经济"})
    assert out[0]["hotel"]["name"] == "如家"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/agent/test_tools.py -k "assemble or assign" -v`
Expected: FAIL，`AttributeError: module ... has no attribute 'assemble_itinerary'`

- [ ] **Step 3: 写实现（追加到 tools.py）**

在 `tools.py` 顶部补 import：

```python
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.planning import (
    cluster_by_day, daily_centers_of, DayPlans, ITINERARY_SYS,
)
from app.agent.lodging import (
    overnight_days, attach_hotels, hotel_keyword, _AccoResult, ACCO_SYS,
)
from app.llm.factory import build_llm
```

追加工具：

```python
@tool
async def assemble_itinerary(city: str, days: int, attractions: list, restaurants: list,
                             weather: dict, start_date: str = "", num_people: int = 1,
                             budget_advice: dict | None = None) -> dict:
    """把景点/餐厅/天气编排成逐日行程。返回 {day_plans, daily_centers}。
    内部先确定性分天聚类，再 LLM 填充时间线与人均 cost。budget_advice 非空时压低花费。"""
    clusters = cluster_by_day(attractions or [], days)
    centers = daily_centers_of(clusters)
    payload = {
        "days": days, "clusters": clusters, "restaurants": restaurants or [],
        "weather": weather or {}, "start_date": start_date, "num_people": max(1, num_people),
    }
    if budget_advice:
        payload["budget_advice"] = budget_advice
    llm = build_llm(temperature=0).with_structured_output(DayPlans, method="function_calling")
    result = await llm.ainvoke([
        SystemMessage(content=ITINERARY_SYS),
        HumanMessage(content=str(payload)),
    ])
    return {
        "day_plans": [d.model_dump(by_alias=True) for d in result.days],
        "daily_centers": centers,
    }


@tool
async def assign_hotels(city: str, day_plans: list, level: str = "舒适",
                        daily_centers: list | None = None) -> list:
    """为过夜日就近分配酒店并嵌入 day_plans。返回更新后的 day_plans；单日游/无行程原样返回。"""
    nights = overnight_days(day_plans)
    if not nights:
        return day_plans
    try:
        pool = await amap.search_poi(city, hotel_keyword(level), "住宿服务") if city else []
    except Exception:  # noqa: BLE001
        pool = []
    payload = {"overnight_days": nights, "level": level,
               "daily_centers": daily_centers or [], "hotel_pool": pool}
    llm = build_llm(temperature=0).with_structured_output(_AccoResult, method="function_calling")
    result = await llm.ainvoke([
        SystemMessage(content=ACCO_SYS),
        HumanMessage(content=str(payload)),
    ])
    assignments = [{"day": a.day, "hotel": a.hotel.model_dump(by_alias=True)}
                   for a in result.assignments]
    return attach_hotels(day_plans, assignments)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/agent/test_tools.py -k "assemble or assign" -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add app/agent/tools.py tests/agent/test_tools.py
git commit -m "feat(react): 编排类工具 assemble_itinerary/assign_hotels"
```

---

## Task 8: 工具层 — 核算 / ask_user / finalize_plan

`compute_budget_tool` 用 `InjectedState` 读 retry_count；`finalize_plan` 用 `InjectedState` 读旧 day_plans + `Command` 写新 state + diff。`ask_user` 用 `interrupt`。

**Files:**
- Modify: `app/agent/tools.py`（追加）
- Test: `tests/agent/test_tools.py`（追加）

**Interfaces:**
- Consumes: `budgeting.compute_budget`；`diffing.diff_changed_days`；`InjectedState`/`Command`/`InjectedToolCallId`/`interrupt`。
- Produces:
  - `compute_budget_tool(day_plans, num_people=1, limit=0.0, state) -> dict` — 返回 `{budget_check, cut_suggestions}`（advice 拆出）。
  - `ask_user(field, question, options=None) -> str` — interrupt 暂停，返回用户答案。
  - `finalize_plan(day_plans, tool_call_id, state) -> Command` — 写 `day_plans/changed_days/plan_version` + ToolMessage。

- [ ] **Step 1: 写失败测试（追加）**

```python
from langgraph.types import Command as _Command


@pytest.mark.asyncio
async def test_compute_budget_tool_reports_over(fake_amap):
    dps = [{"day": 1, "items": [{"type": "attraction", "name": "A", "cost": 5000}]}, {"day": 2, "items": []}]
    out = await tools.compute_budget_tool.ainvoke({
        "day_plans": dps, "num_people": 1, "limit": 100,
        "state": {"retry_count": 0},
    })
    assert out["budget_check"]["over"] is True
    assert isinstance(out["cut_suggestions"], list)


@pytest.mark.asyncio
async def test_finalize_plan_writes_and_diffs(fake_amap):
    new_dps = [{"day": 1, "items": [{"type": "attraction", "name": "故宫", "poi_id": "p1"}]}]
    cmd = await tools.finalize_plan.ainvoke({
        "day_plans": new_dps,
        "state": {"day_plans": [], "plan_version": 0},
        "tool_call_id": "call_x",
    })
    assert isinstance(cmd, _Command)
    assert cmd.update["day_plans"] == new_dps
    assert cmd.update["changed_days"] == [1]
    assert cmd.update["plan_version"] == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/agent/test_tools.py -k "compute_budget_tool or finalize" -v`
Expected: FAIL，`AttributeError`

- [ ] **Step 3: 写实现（追加）**

补 import：

```python
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command, interrupt

from app.agent.budgeting import compute_budget
from app.agent.diffing import diff_changed_days
```

追加工具：

```python
@tool
async def compute_budget_tool(day_plans: list, num_people: int = 1, limit: float = 0.0,
                              state: Annotated[dict, InjectedState] = None) -> dict:
    """核算行程总花费并判定是否超预算。返回 {budget_check, cut_suggestions}。
    超支时 cut_suggestions 给出可削减的高价项；是否重排由你（agent）自主决定。"""
    retry_count = (state or {}).get("retry_count", 0) or 0
    res = compute_budget(day_plans, max(1, num_people), limit or 0.0, retry_count)
    advice = res["advice"] or {}
    return {"budget_check": res["budget_check"], "cut_suggestions": advice.get("cut_suggestions", [])}


@tool
def ask_user(field: str, question: str, options: list | None = None) -> str:
    """信息不足以规划时向用户提问并暂停，等待用户回答。
    field 是缺失要素名（如 city/days/budget），options 为单选项（开放式留空）。"""
    answer = interrupt({"field": field, "question": question, "options": options or []})
    return answer


@tool
async def finalize_plan(day_plans: list,
                        tool_call_id: Annotated[str, InjectedToolCallId],
                        state: Annotated[dict, InjectedState] = None) -> Command:
    """确认最终行程：写入 day_plans，并自动算出本轮变更的 changed_days 供前端增量重绘。
    完成规划或修改后调用一次。"""
    old = (state or {}).get("day_plans", []) or []
    changed = diff_changed_days(old, day_plans)
    old_ver = (state or {}).get("plan_version", 0) or 0
    new_ver = old_ver + (1 if changed else 0)
    return Command(update={
        "day_plans": day_plans,
        "changed_days": changed,
        "plan_version": new_ver,
        "messages": [ToolMessage(
            f"已确认行程，变更天数 {changed or '无'}", tool_call_id=tool_call_id)],
    })
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/agent/test_tools.py -k "compute_budget_tool or finalize" -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 全工具测试 + 提交**

Run: `uv run pytest tests/agent/test_tools.py -v`
Expected: PASS（全部）

```bash
git add app/agent/tools.py tests/agent/test_tools.py
git commit -m "feat(react): 核算/ask_user/finalize_plan 工具"
```

---

## Task 9: 系统提示 `prompt.py`

**Files:**
- Create: `app/agent/prompt.py`
- Test: `tests/agent/test_prompt.py`

**Interfaces:**
- Produces: `TRIP_AGENT_SYS: str` — 引导 agent 自主决策、约束业务规则必须走对应 tool、自主澄清规则、收尾必产最终回复。

- [ ] **Step 1: 写失败测试**

Create `tests/agent/test_prompt.py`:

```python
from app.agent.prompt import TRIP_AGENT_SYS


def test_prompt_covers_key_directives():
    p = TRIP_AGENT_SYS
    # 必须提及关键工具与约束，确保 agent 知道能力边界
    for kw in ("ask_user", "finalize_plan", "compute_budget", "预算", "澄清"):
        assert kw in p, f"系统提示缺少关键指引：{kw}"
    assert len(p) > 200
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/agent/test_prompt.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写实现**

Create `app/agent/prompt.py`:

```python
"""ReAct 旅行 Agent 系统提示：赋予能力 + 约束业务正确性，不强制固定流程。"""

TRIP_AGENT_SYS = (
    "你是一个旅行规划助手，通过调用工具自主完成规划、修改与问答。\n"
    "\n"
    "可用工具：search_attractions / search_restaurants / get_weather / plan_route（检索）；"
    "assemble_itinerary（把检索结果编排成逐日行程）；assign_hotels（为过夜日分配酒店）；"
    "compute_budget（核算花费与超支判定）；ask_user（信息不足时向用户提问）；"
    "finalize_plan（确认最终行程，必须在完成规划或修改后调用一次）。\n"
    "\n"
    "决策原则：\n"
    "1. 自主判断需要哪些工具、调用顺序与次数。规划新行程通常先检索（景点/餐厅/天气）"
    "再 assemble_itinerary，再 assign_hotels，再 compute_budget，最后 finalize_plan。\n"
    "2. 信息不足以规划（如缺城市、天数）时，调用 ask_user 提问；信息足够则直接规划，不要无谓提问。"
    "同一要素不要重复追问，已知信息不要再问。\n"
    "3. 费用核算必须调用 compute_budget，不要自己心算。若返回 over=true，"
    "参考 cut_suggestions 重新 assemble_itinerary（传入 budget_advice）压低花费，"
    "或在最终回复中向用户说明超支情况。\n"
    "4. 修改已有行程时，基于当前行程做局部调整，只改用户要求改的部分，"
    "改完同样调用 finalize_plan。\n"
    "5. 纯问答（询问已有行程、是否合适等）直接回答，不要调用 finalize_plan。\n"
    "\n"
    "完成后，用简体中文输出面向用户的最终回复：规划/修改场景写清晰的逐日攻略，"
    "问答场景直接回答问题。语气友好实用。"
)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/agent/test_prompt.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/agent/prompt.py tests/agent/test_prompt.py
git commit -m "feat(react): TRIP_AGENT_SYS 系统提示"
```

---

## Task 10: 组装 agent `build.py` + 接 `builder.py`

**Files:**
- Create: `app/agent/build.py`
- Modify: `app/graph/builder.py`（整体重写）
- Modify: `app/llm/factory.py`（确认 `disable_streaming=False` 可透传 — 已支持 `**overrides`，加一行测试即可）
- Test: `tests/agent/test_build_agent.py`

**Interfaces:**
- Consumes: `tools.*` 9 工具；`TRIP_AGENT_SYS`；`TripState`；`build_llm`。
- Produces: `build_trip_agent(checkpointer=None) -> CompiledGraph`；`build_graph(checkpointer=None)` 转调它（保持 `main.py` 调用不变）。

- [ ] **Step 1: 写失败测试**

Create `tests/agent/test_build_agent.py`:

```python
from langgraph.checkpoint.memory import MemorySaver


def test_build_graph_returns_compiled_agent(monkeypatch):
    # 不触发真实 LLM：patch build_llm 返回一个可 bind_tools 的占位
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.outputs import ChatResult, ChatGeneration
    from langchain_core.messages import AIMessage

    class _Stub(BaseChatModel):
        @property
        def _llm_type(self): return "stub"
        def bind_tools(self, tools, **kw): return self
        def _generate(self, messages, stop=None, run_manager=None, **kw):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    monkeypatch.setattr("app.agent.build.build_llm", lambda *a, **k: _Stub())
    from app.graph.builder import build_graph
    graph = build_graph(checkpointer=MemorySaver())
    assert hasattr(graph, "astream_events")
    assert hasattr(graph, "aget_state")
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/agent/test_build_agent.py -v`
Expected: FAIL（`build.py` 不存在 / build_graph 仍是旧实现引用已删模块）

- [ ] **Step 3: 写实现**

Create `app/agent/build.py`:

```python
"""组装全局单 Agent ReAct 图：create_agent + 9 工具 + 系统提示 + 业务 state。"""
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver

from app.agent.prompt import TRIP_AGENT_SYS
from app.agent.state import TripState
from app.agent.tools import (
    search_attractions, search_restaurants, get_weather, plan_route,
    assemble_itinerary, assign_hotels, compute_budget_tool, ask_user, finalize_plan,
)
from app.llm.factory import build_llm

_TOOLS = [
    search_attractions, search_restaurants, get_weather, plan_route,
    assemble_itinerary, assign_hotels, compute_budget_tool, ask_user, finalize_plan,
]


def build_trip_agent(checkpointer=None):
    return create_agent(
        model=build_llm(temperature=0, disable_streaming=False),
        tools=_TOOLS,
        system_prompt=TRIP_AGENT_SYS,
        state_schema=TripState,
        checkpointer=checkpointer or MemorySaver(),
    )
```

Rewrite `app/graph/builder.py`（整体替换）:

```python
"""图构建：全局单 Agent ReAct。build_graph 直接返回 create_agent 组装的 agent。

历史上这里是 16 节点固定编排图；ReAct 重构后坍缩为单一 agent（见 app/agent/build.py）。
保留 build_graph(checkpointer) 签名，main.py 无需改动。
"""
from app.agent.build import build_trip_agent


def build_graph(checkpointer=None):
    return build_trip_agent(checkpointer)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/agent/test_build_agent.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/agent/build.py app/graph/builder.py tests/agent/test_build_agent.py
git commit -m "feat(react): build_graph 返回 create_agent 单 Agent"
```

---

## Task 11: 改 `stream.py` token 放行 + summary 取末条 AIMessage

现 `stream.py:49` 只放行 `langgraph_node=="summarize"`；改为放行所有 `on_chat_model_stream` 文本 token（中间思考+最终回复都流）。`EVENT_FINAL` 的 `answer` 从末条 AIMessage 取（不再有 summarize 写 `summary`）。

**Files:**
- Modify: `app/graph/stream.py`
- Modify: `app/core/constants.py`（精简 NODES/NODE_LABELS，删 MAX_CLARIFY_ROUNDS）
- Test: `tests/agent/test_stream_react.py`

**Interfaces:**
- Consumes: `build_graph`（Task 10）；`session_store`（不变）。
- Produces: `sse_events(message, thread_id, request)` 流程不变，仅 token 放行条件与 summary 取值变化。

- [ ] **Step 1: 写失败测试（端到端 SSE，用脚本化可 bind_tools 假模型）**

Create `tests/agent/test_stream_react.py`:

```python
"""端到端：用脚本化假模型驱动 create_agent，验证 SSE token 放行与 EVENT_FINAL。"""
import json

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.messages import AIMessage

_CALLS = {"n": 0}


class _ScriptedModel(BaseChatModel):
    """第一轮直接产最终回复（无 tool_call），逐字流式。"""
    @property
    def _llm_type(self): return "scripted"
    def bind_tools(self, tools, **kw): return self
    def _generate(self, messages, stop=None, run_manager=None, **kw):
        return ChatResult(generations=[ChatGeneration(
            message=AIMessage(content="成都三天行程已为你准备好。"))])


@pytest.fixture
def react_client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    monkeypatch.setenv("AMAP_WEB_KEY", "amap-test-fake")
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "ck.sqlite"))
    monkeypatch.setattr("app.agent.build.build_llm", lambda *a, **k: _ScriptedModel())
    from app.core.config import get_settings
    get_settings.cache_clear()
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def _parse_sse(text):
    events = []
    for block in text.strip().split("\n\n"):
        ev, data = None, None
        for line in block.splitlines():
            if line.startswith("event:"): ev = line[6:].strip()
            elif line.startswith("data:"): data = line[5:].strip()
        if ev: events.append((ev, json.loads(data) if data else None))
    return events


def test_final_answer_from_agent_message(react_client):
    resp = react_client.post("/api/chat", json={"message": "帮我规划成都3天"})
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    names = [e for e, _ in events]
    assert "final" in names
    final = next(d for e, d in events if e == "final")
    assert "成都三天行程" in final["answer"]
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/agent/test_stream_react.py -v`
Expected: FAIL（stream.py 仍按 summarize 放行 / summary 取不到）

- [ ] **Step 3: 改 constants.py**

Modify `app/core/constants.py`：把 `NODES` / `NODE_LABELS` 替换为 ReAct 节点集合，删除 `MAX_CLARIFY_ROUNDS`。替换这两块：

```python
# 图节点全集（create_agent 内部节点：model 决策/回复、tools 执行）
NODES = {"agent", "model", "tools"}

# node_start 携带的友好阶段文案（agent 内部节点较少，仅作兜底）
NODE_LABELS = {
    "agent": "正在思考…",
    "model": "正在思考…",
    "tools": "正在调用工具…",
}
```

删除文件末尾的 `MAX_CLARIFY_ROUNDS = 4` 行。

- [ ] **Step 4: 改 stream.py token 放行 + summary**

Modify `app/graph/stream.py`：

把 token 放行分支（约 49 行）：

```python
            elif kind == "on_chat_model_stream" and ev.get("metadata", {}).get("langgraph_node") == "summarize":
                tok = ev["data"]["chunk"].content
                if tok:
                    yield _sse(EVENT_TOKEN, {"text": tok})
```

改为（放行所有 model 文本 token；工具的 ToolMessage 不走该事件，天然不混入）：

```python
            elif kind == "on_chat_model_stream":
                tok = ev["data"]["chunk"].content
                if tok:
                    yield _sse(EVENT_TOKEN, {"text": tok})
```

把 EVENT_FINAL 的 `answer` 取值（约 64 行 `answer = values.get("summary", "")`）改为从末条 AIMessage 取：

```python
            messages = values.get("messages", []) or []
            answer = ""
            for m in reversed(messages):
                content = getattr(m, "content", None)
                msg_type = getattr(m, "type", "")
                if msg_type == "ai" and content:
                    answer = content
                    break
```

（保留其下 `day_plans = values.get("day_plans", [])` 等不变。）

- [ ] **Step 5: 运行确认通过**

Run: `uv run pytest tests/agent/test_stream_react.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add app/graph/stream.py app/core/constants.py tests/agent/test_stream_react.py
git commit -m "feat(react): stream 放行 agent 文本 token + summary 取末条 AIMessage"
```

---

## Task 12: 死代码清理 + 删旧测试 + 全量绿

删除 spec §11 清单中所有不再进图的节点文件与对应旧测试，确认无残余引用，全量测试通过。

**Files:**
- Delete: `app/graph/nodes/dispatch_agent.py` `dispatch.py` `clarify.py` `retrieve.py` `refine.py` `routing.py` `answer.py` `summarize.py` `memory.py` `memory_update.py` `weather.py` `attractions.py` `restaurants.py` `transport.py` `itinerary.py` `budget.py` `accommodation.py`
- Delete: `app/graph/state.py`（旧 TripState；ReAct 用 `app/agent/state.py`）
- Delete 旧测试: `tests/test_dispatch.py` `test_dispatch_agent.py` `test_dispatch_topology.py` `test_clarify_node.py` `test_clarify_interrupt.py` `test_refine_node.py` `test_refine_search.py` `test_need_routing.py` `test_parallel_retrieval.py` `test_multiturn_qa.py` `test_multiturn_refine.py` `test_multiturn_replan.py` `test_m5fix_e2e.py` `test_summarize.py` `test_builder.py` `test_structured_output_method.py` `test_itinerary.py` `test_cluster_by_day.py` `test_budget.py` `test_accommodation.py`
- Keep: `tests/test_amap.py`（amap 未变）、`tests/test_llm_factory.py`、`tests/test_sessions.py`、`tests/test_sqlite_checkpointer.py`
- 待评估（见 Step 2，依赖旧拓扑则删）：`tests/test_chat_stream.py` `test_chat_stream_m2.py` `test_chat_stream_m4.py` `test_contracts.py`

- [ ] **Step 1: grep 确认无残余 import（删除前体检）**

Run: `uv run python -c "import app.graph.builder; import app.main; print('import OK')"`
Expected: `import OK`（builder 已不依赖任何旧节点）

Run: `grep -rn "from app.graph.nodes" app/ | grep -v test`
Expected: 无输出（生产代码不再 import 任何旧节点）

若有输出，先修复对应引用再继续。

- [ ] **Step 2: 评估并处理依赖旧拓扑的测试**

逐个检查 `tests/test_chat_stream.py` `test_chat_stream_m2.py` `test_chat_stream_m4.py` `test_contracts.py`：

Run: `grep -ln "summarize\|dispatch\|clarify\|refine\|NODE_LABELS\|MAX_CLARIFY\|graph.state" tests/test_chat_stream*.py tests/test_contracts.py`

对命中的测试：断言依赖旧节点名/旧拓扑/旧 NODES 的，删除该测试文件（ReAct 端到端已由 `tests/agent/test_stream_react.py` 覆盖）。

- [ ] **Step 3: 删除节点文件与旧测试**

```bash
git rm app/graph/nodes/dispatch_agent.py app/graph/nodes/dispatch.py \
  app/graph/nodes/clarify.py app/graph/nodes/retrieve.py app/graph/nodes/refine.py \
  app/graph/nodes/routing.py app/graph/nodes/answer.py app/graph/nodes/summarize.py \
  app/graph/nodes/memory.py app/graph/nodes/memory_update.py \
  app/graph/nodes/weather.py app/graph/nodes/attractions.py \
  app/graph/nodes/restaurants.py app/graph/nodes/transport.py \
  app/graph/nodes/itinerary.py app/graph/nodes/budget.py app/graph/nodes/accommodation.py \
  app/graph/state.py
git rm tests/test_dispatch.py tests/test_dispatch_agent.py tests/test_dispatch_topology.py \
  tests/test_clarify_node.py tests/test_clarify_interrupt.py tests/test_refine_node.py \
  tests/test_refine_search.py tests/test_need_routing.py tests/test_parallel_retrieval.py \
  tests/test_multiturn_qa.py tests/test_multiturn_refine.py tests/test_multiturn_replan.py \
  tests/test_m5fix_e2e.py tests/test_summarize.py tests/test_builder.py \
  tests/test_structured_output_method.py tests/test_itinerary.py tests/test_cluster_by_day.py \
  tests/test_budget.py tests/test_accommodation.py
```

（`tests/test_contracts.py` 与 `tests/test_chat_stream*.py` 按 Step 2 结果决定是否 `git rm`。）

若 `app/graph/nodes/__init__.py` 变空，保留空文件或一并 `git rm`（确认无 import 它）。

- [ ] **Step 4: 全量测试绿**

Run: `uv run pytest -v`
Expected: 全部 PASS（agent 新测试 + 保留的 amap/llm_factory/sessions/checkpointer 测试）。若有 import 残余报错，回到 Step 1 修复。

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "refactor(react): 删除全部旧编排节点与死测试，单 Agent 架构落地"
```

---

## Task 13: 前端进度标签对齐（最小改动）

节点集合从 16 个变为 agent 内部 `model`/`tools`，前端按旧节点名映射的进度文案需对齐，避免显示空白/陌生节点名。

**Files:**
- Modify: 前端进度映射处（`grep -rn "dispatch_agent\|retrieve\|node" frontend/src` 定位；通常在处理 `node_start`/`node_end` 事件的组件或 store）
- 不改 SSE 事件类型定义（`EVENT_CLARIFY`/`EVENT_TOKEN`/`EVENT_PLAN_PATCH`/`EVENT_FINAL` 不变）

**Interfaces:**
- Consumes: `node_start` 事件的 `{node, label}`（后端已带 `label`，见 stream.py `_sse(EVENT_NODE_START, {"node": name, "label": NODE_LABELS.get(name,"")})`）。

- [ ] **Step 1: 定位前端节点标签映射**

Run: `grep -rn "dispatch_agent\|检索\|node_start\|nodeLabel\|进度" frontend/src --include=*.ts --include=*.vue`
记录命中文件与行。

- [ ] **Step 2: 改造为通用文案**

若前端硬编码了旧节点名→文案映射：删除旧映射，改为直接显示后端下发的 `label` 字段（后端 `NODE_LABELS` 已给 agent/model/tools 兜底文案）。若前端无硬编码、本就用后端 label，则本步无改动。

具体改法依 Step 1 结果（前端实现未知，按"优先用后端 label、移除前端旧节点名硬编码"原则）。

- [ ] **Step 3: 手动验证（启动前后端，发一条规划请求）**

Run（后端）: `cd backend && uv run dev`
Run（前端）: `cd frontend && npm run dev`
操作：浏览器发"帮我规划成都3天"，确认：进度区不显示陌生/空节点名；攻略文字逐字流出；地图按 changed_days 重绘；若信息不足弹澄清框。

- [ ] **Step 4: 提交**

```bash
git add frontend/src
git commit -m "feat(react): 前端进度标签对齐 agent 节点"
```

---

## Self-Review 结论

- **Spec 覆盖**：§2.4 create_agent→Task 10；§3.1-3.5 工具→Task 6-8；§4.1 state→Task 5 + Task 12（删旧 state）；§5.2 stream→Task 11；§11 删除清单→Task 12；决策 A（diff）→Task 1+8；决策 B（ask_user）→Task 8；决策 C（agent 本体输出+中间文本可见）→Task 11；前端→Task 13。
- **回归保证**：纯函数（cluster_by_day/compute_budget/overnight_days/attach_hotels）迁移时算法逐字节复制，Task 2-4 单测 assert 具体值与旧测试同口径。
- **类型一致性**：工具名 `compute_budget_tool`（避免与纯函数 `compute_budget` 同名）全程一致；`finalize_plan` 返回 `Command`、`ask_user` 返回 str、检索返回 list/dict 在 Task 6-8 与 Task 10 `_TOOLS` 列表一致。
- **Task 0**：已在 writing-plans 前于真实环境（uv run）验证通过，结论写入 spec §2.4，故本计划不再设独立 Task 0。
