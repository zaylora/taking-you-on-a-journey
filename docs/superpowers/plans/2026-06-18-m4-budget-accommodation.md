# M4 住宿 + 预算闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 7 步编排上接通 `accommodation`（住宿）与 `budget`（预算核算）两节点 + 超支回退条件边，前端展示预算明细、超支提示与每日酒店。

**Architecture:** 费用由 LLM 估单价（itinerary 给每项 `cost`、accommodation 给酒店 `price`），`budget` 节点做纯函数汇总核算；超支时 `budget` 算出超支额 + 确定性挑「最贵可削减项」写入 `budget_advice`，回退 `itinerary` 让 LLM 参考建议重排，`retry_count ≤ 2` 封顶。酒店嵌进每天 `day_plans[i].hotel`。前端消费 `final` 新增的 `budget` 字段渲染总览条 + 超支提示，每天时间线末尾渲染酒店卡。

**Tech Stack:** 后端 Python ≥3.10 · uv · LangGraph（StateGraph + MemorySaver + 条件边/环）· LangChain structured output（Pydantic `function_calling`）· pytest + pytest-asyncio。前端 Vue 3 `<script setup>` · Pinia · TypeScript · Element Plus · Vite · bun。

## Global Constraints

- 全程界面文案、提示词与注释用**简体中文**，永不使用日语。
- 费用全部由 LLM 估算（高德无价格数据）；`budget` 节点是**纯函数**，不调 LLM、不做 I/O。
- `PlanItem.cost` = 人均花费（元）；`Hotel.price` = 每晚整间价（元）。`estimated = num_people × Σ(items.cost) + Σ(hotel.price)`。
- 预算口径：`state["budget"]` 是**总预算（元）**，`0` 表示**不限**（`over` 恒 False、不回退）。
- 过夜日 = 除最后一天外的每天（`day ∈ [1, days-1]`）；单日游无住宿。
- 回退计数语义收在 `budget` 节点内：`retry = over and retry_count < 2`，`retry` 为真时 `retry_count += 1` 并写 `budget_advice`；`route_after_budget` 只读 `budget_check["retry"]` 布尔，不做算术。
- 单个外部检索失败走降级、不抛（沿用 M2）；高德酒店 POI 失败/空 → accommodation 仍交 LLM 生成「参考酒店」。
- 后端测试一律对 LLM（`build_llm`）与高德 tool（`app.tools.amap`）打桩，不依赖真实 Key/网络。
- 前端无单测框架：每个前端任务的验证 = `bun run build`（`vue-tsc -b && vite build`，类型即契约）通过 + 指定手动验收。前端命令在 `frontend/` 目录执行。
- 设计文档：`docs/superpowers/specs/2026-06-18-m4-budget-accommodation-design.md`。

---

### Task 1: itinerary 扩展费用字段 + Hotel 模型 + 回退建议入 prompt

**Files:**
- Modify: `backend/app/graph/nodes/itinerary.py`
- Test: `backend/tests/test_itinerary.py`

**Interfaces:**
- Consumes: 现有 `Location`、`DayWeather`、`PlanItem`、`DayPlan`、`DayPlans`、`cluster_by_day`、`build_llm`。
- Produces（后续任务依赖的确切名字与类型）：
  - `PlanItem.cost: float`（默认 0.0）。
  - `class Hotel(BaseModel)`：字段 `name:str`、`poi_id:str`、`location:Location`、`price:float`、`level:str`（均有默认）。
  - `DayPlan.hotel: Hotel | None`（默认 None）。
  - `_build_payload(state: dict, clusters: list) -> dict`：构造传给 LLM 的 payload；当 `state["budget_advice"]` 存在时在 payload 加 `"budget_advice"` 键。

- [ ] **Step 1: 写失败测试（cost/hotel 字段 + payload 注入建议）**

在 `backend/tests/test_itinerary.py` 末尾追加：

```python
def test_plan_item_and_hotel_carry_cost_and_hotel():
    from app.graph.nodes.itinerary import PlanItem, Hotel, DayPlan, Location
    item = PlanItem(type="attraction", name="武侯祠", poi_id="B1",
                    location=Location(lng=104.0, lat=30.6), cost=60.0)
    assert item.cost == 60.0
    hotel = Hotel(name="如家", poi_id="H1", location=Location(lng=104.0, lat=30.6),
                  price=400.0, level="舒适")
    dp = DayPlan(day=1, center=Location(), items=[item], hotel=hotel)
    dumped = dp.model_dump(by_alias=True)
    assert dumped["items"][0]["cost"] == 60.0
    assert dumped["hotel"]["price"] == 400.0
    assert DayPlan(day=2, center=Location(), items=[]).hotel is None


def test_build_payload_injects_budget_advice():
    from app.graph.nodes.itinerary import _build_payload
    base = {"days": 2, "num_people": 2}
    assert "budget_advice" not in _build_payload(base, [])
    with_advice = {**base, "budget_advice": {"over_amount": 500.0, "cut_suggestions": []}}
    p = _build_payload(with_advice, [])
    assert p["budget_advice"]["over_amount"] == 500.0
    assert p["num_people"] == 2
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && uv run pytest tests/test_itinerary.py -q`
Expected: FAIL（`Hotel` 不存在 / `_build_payload` 不存在 / `cost` 字段缺失）。

- [ ] **Step 3: 实现 itinerary 修改**

在 `backend/app/graph/nodes/itinerary.py` 中：

3a. 给 `PlanItem` 在 `note` 字段后追加 `cost` 字段：

```python
    cost: float = Field(default=0.0, description="该项人均花费(元)：门票/餐标/市内交通；免费景点或交通项填 0")
```

3b. 在 `class DayPlan` **之前**新增 `Hotel` 模型：

```python
class Hotel(BaseModel):
    name: str = Field(default="", description="酒店名称，沿用候选池，不要编造")
    poi_id: str = Field(default="", description="高德 POI id；降级参考酒店可留空")
    location: Location = Field(default_factory=Location, description="酒店经纬度")
    price: float = Field(default=0.0, description="每晚整间价(元)，按住宿档位估")
    level: str = Field(default="", description="住宿档位：经济/舒适/高端")
```

3c. 给 `DayPlan` 追加 `hotel` 字段（放在 `items` 字段之后）：

```python
    hotel: Hotel | None = Field(default=None, description="当晚住宿；离程日/单日游为 None")
```

3d. 替换 `_SYS` 常量为（增加费用与回退建议指引）：

```python
_SYS = (
    "你是行程编排助手。给定每天的景点簇、餐厅候选、交通与天气，为每天安排合理的时间线："
    "上午/下午景点、午餐/晚餐就近分配餐厅、必要的市内交通。雨天优先室内项。"
    "为每个行程项估算人均花费 cost（元）：门票按景点合理价、餐标按餐厅档位、市内交通按方式估；"
    "免费景点或无费用项填 0。"
    "若输入含 budget_advice（上轮超支额与削减建议），据此压低总花费："
    "优先减少或替换高价付费景点、降低餐标、精简交通。"
    "输出严格符合给定结构（含每项的 location 经纬度与 cost，沿用输入坐标）。"
)
```

3e. 在 `async def itinerary` **之前**新增纯函数 `_build_payload`：

```python
def _build_payload(state: dict, clusters: list) -> dict:
    """构造传给 LLM 的输入 payload；回退时带上 budget_advice。纯函数，便于单测。"""
    payload = {
        "days": state.get("days", 3) or 3,
        "clusters": clusters,
        "restaurants": state.get("restaurants", []),
        "transport": state.get("transport", {}),
        "weather": state.get("weather", {}),
        "start_date": state.get("start_date", ""),
        "num_people": state.get("num_people", 1) or 1,
    }
    advice = state.get("budget_advice")
    if advice:
        payload["budget_advice"] = advice
    return payload
```

3f. 把 `itinerary` 函数体里原来内联构造 `payload` 的部分改为调用 `_build_payload`。将：

```python
    llm = build_llm(temperature=0).with_structured_output(DayPlans, method="function_calling")
    payload = {
        "days": days,
        "clusters": clusters,
        "restaurants": state.get("restaurants", []),
        "transport": state.get("transport", {}),
        "weather": state.get("weather", {}),
        "start_date": state.get("start_date", ""),
    }
```

替换为：

```python
    llm = build_llm(temperature=0).with_structured_output(DayPlans, method="function_calling")
    payload = _build_payload(state, clusters)
```

（`days`/`clusters`/`daily_centers` 上方逻辑保持不变。）

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd backend && uv run pytest tests/test_itinerary.py -q`
Expected: PASS（含原有 `test_itinerary_produces_day_plans`，因 `cost` 默认 0 不破坏旧断言）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/nodes/itinerary.py backend/tests/test_itinerary.py
git commit -m "feat(m4): itinerary 加 PlanItem.cost + Hotel 模型 + DayPlan.hotel + 回退建议入 prompt" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: budget 节点（纯函数核算 + 超支回退判定 + 路由）

**Files:**
- Modify: `backend/app/graph/nodes/budget.py`（替换占位实现）
- Test: `backend/tests/test_budget.py`（新建）

**Interfaces:**
- Consumes: `state` 里的 `day_plans`（含 `items[].cost`、`hotel.price`）、`num_people`、`budget`、`retry_count`。
- Produces（后续依赖）：
  - `_sum_costs(day_plans: list, num_people: int) -> dict`：返回 `{"breakdown": {ticket,food,transport,hotel}, "estimated": float}`。
  - `_pick_cut_suggestions(day_plans: list, top: int = 3) -> list`。
  - `compute_budget(day_plans: list, num_people: int, limit: float, retry_count: int) -> dict`：返回 `{"budget_check": dict, "advice": dict|None, "retry_count": int}`。
  - `budget(state) -> dict`：节点；输出含 `budget_check`、`retry_count`，回退时含 `budget_advice`。
  - `route_after_budget(state) -> str`：返回 `"itinerary"` 或 `"summarize"`。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_budget.py`：

```python
from app.graph.nodes.budget import (
    compute_budget, budget, route_after_budget, _sum_costs,
)


def _day(day, items, hotel=None):
    d = {"day": day, "items": items}
    if hotel is not None:
        d["hotel"] = hotel
    return d


def _item(type_, name, cost):
    return {"type": type_, "name": name, "cost": cost}


def test_sum_costs_classifies_and_multiplies_by_people():
    dps = [_day(1, [_item("attraction", "A", 100), _item("meal", "M", 50),
                    _item("transport", "", 10)], hotel={"price": 400})]
    s = _sum_costs(dps, num_people=2)
    assert s["breakdown"] == {"ticket": 200, "food": 100, "transport": 20, "hotel": 400}
    assert s["estimated"] == 720  # (100+50+10)*2 + 400


def test_under_budget_no_over_no_retry():
    dps = [_day(1, [_item("attraction", "A", 100)], hotel={"price": 200})]
    res = compute_budget(dps, num_people=1, limit=1000, retry_count=0)
    assert res["budget_check"]["over"] is False
    assert res["budget_check"]["retry"] is False
    assert res["advice"] is None
    assert res["retry_count"] == 0


def test_over_budget_triggers_retry_with_advice():
    dps = [_day(1, [_item("attraction", "A", 800), _item("meal", "M", 300)],
                hotel={"price": 1000})]
    res = compute_budget(dps, num_people=1, limit=1000, retry_count=0)
    bc = res["budget_check"]
    assert bc["over"] is True and bc["retry"] is True
    assert bc["retry_count"] == 1
    assert res["advice"]["over_amount"] == bc["estimated"] - 1000
    assert res["advice"]["cut_suggestions"][0]["name"] == "A"  # 最贵项排前


def test_limit_zero_means_unlimited():
    dps = [_day(1, [_item("attraction", "A", 99999)], hotel={"price": 99999})]
    res = compute_budget(dps, num_people=2, limit=0, retry_count=0)
    assert res["budget_check"]["over"] is False
    assert res["budget_check"]["retry"] is False


def test_retry_cap_at_two_sets_note():
    dps = [_day(1, [_item("attraction", "A", 5000)])]
    res = compute_budget(dps, num_people=1, limit=1000, retry_count=2)
    bc = res["budget_check"]
    assert bc["over"] is True
    assert bc["retry"] is False            # 到顶不再回退
    assert bc["retry_count"] == 2
    assert bc["note"].startswith("已尽力压缩")


def test_node_emits_advice_only_when_retry():
    over_state = {"day_plans": [_day(1, [_item("attraction", "A", 5000)])],
                  "num_people": 1, "budget": 1000, "retry_count": 0}
    out = budget(over_state)
    assert out["retry_count"] == 1 and "budget_advice" in out
    under_state = {"day_plans": [_day(1, [_item("attraction", "A", 10)])],
                   "num_people": 1, "budget": 1000, "retry_count": 0}
    assert "budget_advice" not in budget(under_state)


def test_route_reads_retry_flag():
    assert route_after_budget({"budget_check": {"retry": True}}) == "itinerary"
    assert route_after_budget({"budget_check": {"retry": False}}) == "summarize"
    assert route_after_budget({}) == "summarize"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && uv run pytest tests/test_budget.py -q`
Expected: FAIL（`compute_budget` 等未定义 / 占位 `budget` 返回 `{}`）。

- [ ] **Step 3: 实现 budget 节点**

整体替换 `backend/app/graph/nodes/budget.py`：

```python
"""budget 节点（M4）：纯函数汇总核算 + 超支回退判定 + 路由。

费用口径（设计文档 §2）：cost 为人均、hotel.price 为每晚整间价；
estimated = num_people × Σ(人均项) + Σ(hotel.price)；limit==0 表示不限。
回退计数收在本节点内（设计文档 §1）：over 且 retry_count<2 → retry，且 retry_count+1、写 advice。
"""
from app.graph.state import TripState

_MAX_RETRY = 2


def _sum_costs(day_plans: list, num_people: int) -> dict:
    """汇总 breakdown（人均项已 ×人数）与总额 estimated。纯函数。"""
    ticket = food = transport = hotel = 0.0
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
        if h:
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
    """确定性挑出最贵可削减项（付费景点/餐饮），按 cost 降序取前 top 个。"""
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
        "limit": round(limit, 2),
        "estimated": estimated,
        "over": over,
        "retry": retry,
        "breakdown": sums["breakdown"],
        "retry_count": new_count,
        "note": note,
    }
    advice = None
    if retry:
        advice = {"over_amount": round(estimated - limit, 2),
                  "cut_suggestions": _pick_cut_suggestions(day_plans)}
    return {"budget_check": budget_check, "advice": advice, "retry_count": new_count}


def budget(state: TripState) -> dict:
    day_plans = state.get("day_plans", []) or []
    num_people = state.get("num_people", 1) or 1
    limit = state.get("budget", 0.0) or 0.0
    retry_count = state.get("retry_count", 0) or 0
    res = compute_budget(day_plans, num_people, limit, retry_count)
    out = {"budget_check": res["budget_check"], "retry_count": res["retry_count"]}
    if res["advice"] is not None:
        out["budget_advice"] = res["advice"]
    return out


def route_after_budget(state: TripState) -> str:
    return "itinerary" if state.get("budget_check", {}).get("retry") else "summarize"
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd backend && uv run pytest tests/test_budget.py -q`
Expected: PASS（7 个用例全绿）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/nodes/budget.py backend/tests/test_budget.py
git commit -m "feat(m4): budget 纯函数核算 + 超支回退判定 + route_after_budget" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: accommodation 节点（POI 检索 + LLM 按档位/就近分配 + 嵌回 day_plans）

**Files:**
- Modify: `backend/app/graph/nodes/accommodation.py`（替换占位实现）
- Test: `backend/tests/test_accommodation.py`（新建）

**Interfaces:**
- Consumes: `itinerary.Hotel`、`itinerary.Location`（Task 1）；`build_llm`；`app.tools.amap.search_poi`；`state` 的 `day_plans`、`daily_centers`、`city`、`preferences`。
- Produces（后续依赖）：
  - `overnight_days(day_plans: list) -> list[int]`。
  - `hotel_keyword(level: str) -> str`。
  - `attach_hotels(day_plans: list, assignments: list) -> list`（`assignments` 为 `[{"day": int, "hotel": dict}]`）。
  - `class _AccoResult` / `class _HotelForDay`（LLM 结构化输出 schema）。
  - `async def accommodation(state, config) -> dict`：输出 `{"day_plans": <已嵌 hotel>}`；无过夜日时返回 `{}`。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_accommodation.py`：

```python
import pytest
from app.graph.nodes import accommodation as acc_mod
from app.graph.nodes.accommodation import (
    accommodation, overnight_days, hotel_keyword, attach_hotels, _AccoResult, _HotelForDay,
)
from app.graph.nodes.itinerary import Hotel, Location


def test_overnight_days_excludes_last():
    assert overnight_days([{"day": 1}, {"day": 2}, {"day": 3}]) == [1, 2]
    assert overnight_days([{"day": 1}]) == []
    assert overnight_days([]) == []


def test_hotel_keyword_maps_levels():
    assert hotel_keyword("经济") == "经济型酒店"
    assert hotel_keyword("舒适") == "舒适型酒店"
    assert hotel_keyword("高端") == "高档酒店"
    assert hotel_keyword("未知") == "酒店"


def test_attach_hotels_merges_into_matching_day_without_mutating():
    dps = [{"day": 1, "items": []}, {"day": 2, "items": []}]
    out = attach_hotels(dps, [{"day": 1, "hotel": {"name": "如家", "price": 400}}])
    assert out[0]["hotel"]["name"] == "如家"
    assert "hotel" not in out[1]
    assert "hotel" not in dps[0]  # 不改原对象


@pytest.mark.asyncio
async def test_accommodation_assigns_hotels_to_overnight_days(fake_amap, monkeypatch):
    from tests.conftest import make_fake_build_llm
    fake_amap["search_poi"] = [{"name": "如家", "poi_id": "H1", "lng": 104.0, "lat": 30.6,
                                "address": "", "type": "住宿服务"}]
    result = _AccoResult(assignments=[
        _HotelForDay(day=1, hotel=Hotel(name="如家", poi_id="H1",
                                        location=Location(lng=104.0, lat=30.6),
                                        price=500.0, level="舒适"))])
    monkeypatch.setattr(acc_mod, "build_llm", make_fake_build_llm(structured=result))
    state = {"city": "成都", "preferences": {"住宿": "舒适"},
             "daily_centers": [{"lng": 104.0, "lat": 30.6}, {"lng": 104.1, "lat": 30.7}],
             "day_plans": [{"day": 1, "items": []}, {"day": 2, "items": []}]}
    out = await accommodation(state, None)
    dp = out["day_plans"]
    assert dp[0]["hotel"]["name"] == "如家" and dp[0]["hotel"]["price"] == 500.0
    assert "hotel" not in dp[1]  # 最后一天离程不住


@pytest.mark.asyncio
async def test_single_day_no_hotel(fake_amap, monkeypatch):
    from tests.conftest import make_fake_build_llm
    monkeypatch.setattr(acc_mod, "build_llm", make_fake_build_llm(structured=_AccoResult()))
    out = await accommodation({"city": "成都", "day_plans": [{"day": 1, "items": []}]}, None)
    assert out == {}


@pytest.mark.asyncio
async def test_poi_empty_still_produces_reference_hotel(fake_amap, monkeypatch):
    from tests.conftest import make_fake_build_llm
    fake_amap["search_poi"] = []  # POI 空 → 降级，仍交 LLM 生成参考酒店
    result = _AccoResult(assignments=[
        _HotelForDay(day=1, hotel=Hotel(name="参考酒店", price=300.0, level="经济"))])
    monkeypatch.setattr(acc_mod, "build_llm", make_fake_build_llm(structured=result))
    out = await accommodation({"city": "成都", "preferences": {"住宿": "经济"},
                               "daily_centers": [{"lng": 104.0, "lat": 30.6}],
                               "day_plans": [{"day": 1, "items": []}, {"day": 2, "items": []}]},
                              None)
    assert out["day_plans"][0]["hotel"]["name"] == "参考酒店"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && uv run pytest tests/test_accommodation.py -q`
Expected: FAIL（`overnight_days` 等未定义 / 占位 `accommodation` 返回 `{}`）。

- [ ] **Step 3: 实现 accommodation 节点**

整体替换 `backend/app/graph/nodes/accommodation.py`：

```python
"""accommodation 节点（M4）：高德 POI 检索酒店候选 + LLM 按档位/就近分配到每个过夜日，嵌回 day_plans。

过夜日 = 除最后一天外的每天（离程日不住）；单日游无住宿。
POI 检索失败/空 → LLM 仅按档位 + 每日中心坐标生成「参考酒店」，不阻断。
"""
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.graph.nodes.itinerary import Hotel, Location
from app.llm.factory import build_llm
from app.tools import amap

_LEVEL_KEYWORD = {"经济": "经济型酒店", "舒适": "舒适型酒店", "高端": "高档酒店"}

_SYS = (
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
    """把 assignments（[{day, hotel}]）的 hotel 嵌入对应天，返回新 day_plans。纯函数、不改原对象。"""
    by_day = {a["day"]: a["hotel"] for a in assignments}
    out = []
    for d in day_plans:
        dd = dict(d)
        if d.get("day") in by_day:
            dd["hotel"] = by_day[d["day"]]
        out.append(dd)
    return out


async def accommodation(state, config) -> dict:
    day_plans = state.get("day_plans", []) or []
    nights = overnight_days(day_plans)
    if not nights:
        return {}  # 单日游或无行程 → 无住宿
    city = state.get("city", "")
    prefs = state.get("preferences", {}) or {}
    level = prefs.get("住宿") or prefs.get("accommodation") or "舒适"
    try:
        pool = await amap.search_poi(city, hotel_keyword(level), "住宿服务") if city else []
    except Exception:  # noqa: BLE001 —— 降级，仍交 LLM 生成参考酒店
        pool = []
    llm = build_llm(temperature=0).with_structured_output(_AccoResult, method="function_calling")
    payload = {
        "overnight_days": nights,
        "level": level,
        "daily_centers": state.get("daily_centers", []) or [],
        "hotel_pool": pool,
    }
    result = await llm.ainvoke([
        SystemMessage(content=_SYS),
        HumanMessage(content=str(payload)),
    ], config=config)
    assignments = [{"day": a.day, "hotel": a.hotel.model_dump(by_alias=True)}
                   for a in result.assignments]
    return {"day_plans": attach_hotels(day_plans, assignments)}
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd backend && uv run pytest tests/test_accommodation.py -q`
Expected: PASS（6 个用例全绿）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/nodes/accommodation.py backend/tests/test_accommodation.py
git commit -m "feat(m4): accommodation 高德POI候选 + LLM按档位/就近分配 + 嵌回day_plans" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: State 字段 + 常量 + 图接线（含超支回退条件边）

**Files:**
- Modify: `backend/app/graph/state.py`
- Modify: `backend/app/core/constants.py`
- Modify: `backend/app/graph/builder.py`
- Test: `backend/tests/test_builder.py`

**Interfaces:**
- Consumes: `accommodation.accommodation`（Task 3）、`budget.budget`、`budget.route_after_budget`（Task 2）。
- Produces: 编译后的图含 `accommodation`/`budget` 节点；边 `itinerary→accommodation`、`accommodation→budget`、条件边 `budget→{itinerary, summarize}`；旧 `itinerary→summarize` 删除。State 新增 `budget_check`/`retry_count`/`budget_advice`。

- [ ] **Step 1: 改写 test_builder.py（失败测试）**

整体替换 `backend/tests/test_builder.py`：

```python
from app.graph.builder import build_graph


def test_graph_compiles_with_checkpointer():
    g = build_graph()
    assert g.checkpointer is not None  # MemorySaver 已挂


def test_graph_has_all_core_nodes():
    g = build_graph()
    nodes = set(g.get_graph().nodes.keys())
    for n in ("clarify", "dispatch", "weather", "attractions",
              "restaurants", "transport", "itinerary", "summarize"):
        assert n in nodes


def test_graph_has_m4_accommodation_and_budget_edges():
    g = build_graph()
    gg = g.get_graph()
    nodes = set(gg.nodes.keys())
    assert "accommodation" in nodes and "budget" in nodes
    edges = {(e.source, e.target) for e in gg.edges}
    assert ("itinerary", "accommodation") in edges
    assert ("accommodation", "budget") in edges
    assert ("itinerary", "summarize") not in edges          # 旧直连已删
    budget_targets = {t for (s, t) in edges if s == "budget"}
    assert {"itinerary", "summarize"} <= budget_targets     # 超支条件边两个去向
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && uv run pytest tests/test_builder.py -q`
Expected: FAIL（`accommodation`/`budget` 未接线；`itinerary→summarize` 仍存在）。

- [ ] **Step 3: State 落定 M4 字段**

修改 `backend/app/graph/state.py`，把文件末尾的注释占位：

```python
    # —— M4 预留（注释占位）——
    # hotels: list
    # budget_check: dict
    # retry_count: int
```

替换为：

```python
    # —— M4：住宿嵌入 day_plans + 预算核算 + 超支回退 ——
    budget_check: dict          # {limit,estimated,over,retry,breakdown,retry_count,note}
    retry_count: int            # 已回退次数，budget 节点维护（last-write-wins）
    budget_advice: dict         # {over_amount, cut_suggestions}；itinerary 回退时读
```

- [ ] **Step 4: 常量加入两节点**

修改 `backend/app/core/constants.py`：

4a. 把 `NODES` 改为（加 `accommodation`、`budget`）：

```python
NODES = {"clarify", "dispatch", "weather", "attractions",
         "restaurants", "transport", "itinerary", "accommodation", "budget", "summarize"}
```

4b. 在 `NODE_LABELS` 字典里 `"itinerary"` 行与 `"summarize"` 行之间插入两行：

```python
    "accommodation": "正在挑选住宿…",
    "budget": "正在核算预算…",
```

- [ ] **Step 5: builder 接线**

修改 `backend/app/graph/builder.py`：

5a. 在现有 import 段（`from app.graph.nodes.itinerary import itinerary` 之后、`from app.graph.nodes.summarize import summarize` 之前）加入：

```python
from app.graph.nodes.accommodation import accommodation
from app.graph.nodes.budget import budget, route_after_budget
```

5b. 把节点注册列表改为（加 `accommodation`、`budget`）：

```python
    for name, fn in [
        ("clarify", clarify), ("dispatch", dispatch),
        ("weather", weather), ("attractions", attractions),
        ("restaurants", restaurants), ("transport", transport),
        ("itinerary", itinerary), ("accommodation", accommodation),
        ("budget", budget), ("summarize", summarize),
    ]:
        g.add_node(name, fn)
```

5c. 把并行汇入与收尾段：

```python
    for n in ("weather", "attractions", "restaurants", "transport"):
        g.add_edge("dispatch", n)
        g.add_edge(n, "itinerary")
    g.add_edge("itinerary", "summarize")
    g.add_edge("summarize", END)
    return g.compile(checkpointer=MemorySaver())
```

替换为：

```python
    for n in ("weather", "attractions", "restaurants", "transport"):
        g.add_edge("dispatch", n)
        g.add_edge(n, "itinerary")
    g.add_edge("itinerary", "accommodation")
    g.add_edge("accommodation", "budget")
    g.add_conditional_edges("budget", route_after_budget,
                            {"itinerary": "itinerary", "summarize": "summarize"})
    g.add_edge("summarize", END)
    return g.compile(checkpointer=MemorySaver())
```

- [ ] **Step 6: 运行测试，确认通过**

Run: `cd backend && uv run pytest tests/test_builder.py -q`
Expected: PASS（3 个用例全绿）。

- [ ] **Step 7: 跑全量后端测试，确认无回归**

Run: `cd backend && uv run pytest -q`
Expected: 全绿。特别确认 `test_chat_stream_m2.py` 仍通过——该测试 `days=1`，过夜日为空 → accommodation 提前 `return {}` 不调 LLM；budget 算得 estimated=0 不超支 → 路由 summarize，M2 断言不受影响。

- [ ] **Step 8: Commit**

```bash
git add backend/app/graph/state.py backend/app/core/constants.py backend/app/graph/builder.py backend/tests/test_builder.py
git commit -m "feat(m4): State 加预算字段 + 常量两节点 + 图接 accommodation/budget 超支回退边" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: stream 桥接层 final 携带 budget + 端到端测试

**Files:**
- Modify: `backend/app/graph/stream.py`
- Test: `backend/tests/test_chat_stream_m4.py`（新建）

**Interfaces:**
- Consumes: 编译图（Task 4）；`snap.values["budget_check"]`、`["day_plans"]`、`["summary"]`。
- Produces: `final` 事件 data 由 `{answer, day_plans}` 扩为 `{answer, day_plans, budget}`。

- [ ] **Step 1: 写失败测试（端到端）**

新建 `backend/tests/test_chat_stream_m4.py`：

```python
"""M4 端到端：final 携 budget + day_plans 含 hotel/cost；超支触发回退并封顶。"""
import json
import re


def _extract_final(body: str) -> dict:
    m = re.search(r"event: final\r?\ndata: (.+)", body)
    assert m, f"no final event in:\n{body}"
    return json.loads(m.group(1).strip())


def _stub(monkeypatch, *, item_cost, hotel_price, budget_limit, days=2, num_people=2):
    from app.graph.nodes import (clarify as c, dispatch as d, itinerary as it,
                                  accommodation as acc, summarize as s)
    from app.graph.nodes.dispatch import NormalizedReq
    from app.graph.nodes.itinerary import DayPlans, DayPlan, PlanItem, Location, DayWeather, Hotel
    from app.graph.nodes.accommodation import _AccoResult, _HotelForDay
    from tests.conftest import make_fake_build_llm

    async def no_gaps(_state):
        return []
    monkeypatch.setattr(c, "_evaluate_gaps", no_gaps)
    monkeypatch.setattr(d, "build_llm", make_fake_build_llm(
        structured=NormalizedReq(city="成都", days=days, num_people=num_people,
                                 preferences={"住宿": "舒适"}, budget=float(budget_limit))))
    dp_days = [DayPlan(day=i + 1, weather=DayWeather(), center=Location(lng=104.0, lat=30.6),
                       items=[PlanItem(type="attraction", name=f"景点{i+1}", poi_id=f"B{i+1}",
                                       location=Location(lng=104.0, lat=30.6),
                                       cost=float(item_cost))])
               for i in range(days)]
    monkeypatch.setattr(it, "build_llm", make_fake_build_llm(structured=DayPlans(days=dp_days)))
    monkeypatch.setattr(acc, "build_llm", make_fake_build_llm(structured=_AccoResult(assignments=[
        _HotelForDay(day=1, hotel=Hotel(name="如家", poi_id="H1",
                                        location=Location(lng=104.0, lat=30.6),
                                        price=float(hotel_price), level="舒适"))])))
    monkeypatch.setattr(s, "build_llm", make_fake_build_llm(tokens=["行程", "攻略"]))


def test_final_carries_budget_and_hotel_under_budget(client, fake_amap, monkeypatch):
    fake_amap["search_poi"] = [{"name": "景点1", "poi_id": "B1", "lng": 104.0, "lat": 30.6,
                                "address": "", "type": ""}]
    # estimated = 2人 ×(2天×100) + 400 = 800 < 2000
    _stub(monkeypatch, item_cost=100, hotel_price=400, budget_limit=2000)
    body = client.post("/api/chat", json={"message": "成都2天2人预算2000"}).text
    final = _extract_final(body)
    assert "budget" in final and final["budget"]["over"] is False
    assert final["budget"]["estimated"] == 800
    assert final["day_plans"][0]["hotel"]["name"] == "如家"   # 酒店嵌进 day1
    assert "hotel" not in final["day_plans"][1] or final["day_plans"][1]["hotel"] is None
    assert final["day_plans"][0]["items"][0]["cost"] == 100


def test_over_budget_retries_then_caps(client, fake_amap, monkeypatch):
    fake_amap["search_poi"] = [{"name": "景点1", "poi_id": "B1", "lng": 104.0, "lat": 30.6,
                                "address": "", "type": ""}]
    # estimated = 2人 ×(2天×500) + 1000 = 3000 > 1000；每轮重排同样昂贵 → 封顶
    _stub(monkeypatch, item_cost=500, hotel_price=1000, budget_limit=1000)
    body = client.post("/api/chat", json={"message": "成都2天2人预算1000"}).text
    final = _extract_final(body)
    assert final["budget"]["over"] is True
    assert final["budget"]["retry_count"] == 2          # 回退 2 次后封顶
    assert final["budget"]["note"].startswith("已尽力压缩")
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && uv run pytest tests/test_chat_stream_m4.py -q`
Expected: FAIL（`final` 缺 `budget` 键 → `assert "budget" in final` 失败；或 KeyError）。

- [ ] **Step 3: 实现 stream final 扩展**

修改 `backend/app/graph/stream.py`，把流后判定的 `else` 分支：

```python
        else:
            answer = (snap.values or {}).get("summary", "")
            day_plans = (snap.values or {}).get("day_plans", [])
            yield _sse(EVENT_FINAL, {"answer": answer, "day_plans": day_plans})
```

替换为：

```python
        else:
            answer = (snap.values or {}).get("summary", "")
            day_plans = (snap.values or {}).get("day_plans", [])
            budget = (snap.values or {}).get("budget_check", {})
            yield _sse(EVENT_FINAL, {"answer": answer, "day_plans": day_plans, "budget": budget})
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd backend && uv run pytest tests/test_chat_stream_m4.py -q`
Expected: PASS（2 个用例全绿，含回退封顶路径）。

- [ ] **Step 5: 全量后端测试**

Run: `cd backend && uv run pytest -q`
Expected: 全绿（所有 M1/M2/M4 测试）。

- [ ] **Step 6: Commit**

```bash
git add backend/app/graph/stream.py backend/tests/test_chat_stream_m4.py
git commit -m "feat(m4): final 事件携 budget + M4 端到端测试（超支回退封顶）" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: 前端数据层（类型 + store + useSSE + 进度标签）

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/stores/trip.ts`
- Modify: `frontend/src/composables/useSSE.ts`
- Modify: `frontend/src/components/AgentProgress.vue`

**Interfaces:**
- Consumes: 后端 `final` 的 `budget` 字段（结构见设计文档 §3.3）与 `day_plans[i].hotel`、`items[].cost`。
- Produces: 类型 `Hotel`/`BudgetBreakdown`/`Budget`、`TripItem.cost?`、`DayPlan.hotel?`、`FinalPayload.budget?`；store `budget: Ref<Budget|null>` + `setBudget`；`useSSE` final 分支写 budget；进度条 `accommodation`/`budget` 中文标签。

- [ ] **Step 1: 扩展 types/index.ts**

修改 `frontend/src/types/index.ts`：

1a. 给 `TripItem` 加 `cost?` 字段（在 `indoor?` 行后）：

```ts
export interface TripItem {
  type: 'attraction' | 'meal'
  name: string
  poi_id: string
  location: LngLat
  indoor?: boolean        // 仅 attraction 有
  cost?: number           // 人均花费(元)，M4
}
```

1b. 在 `DayPlan` 之前新增 `Hotel`，并给 `DayPlan` 加 `hotel?`：

```ts
export interface Hotel {
  name: string
  poi_id: string
  location: LngLat
  price: number
  level: string
}
export interface DayPlan {
  day: number
  items: TripItem[]
  center: LngLat
  weather: DayWeather
  hotel?: Hotel | null    // 当晚住宿；离程日为 null，M4
}
```

1c. 新增预算类型，并给 `FinalPayload` 加 `budget?`：

```ts
export interface BudgetBreakdown { ticket: number; hotel: number; food: number; transport: number }
export interface Budget {
  limit: number
  estimated: number
  over: boolean
  breakdown: BudgetBreakdown
  retry_count: number
  note: string
}
```

把原有：

```ts
export interface FinalPayload { answer: string; day_plans?: DayPlan[] }
```

改为：

```ts
export interface FinalPayload { answer: string; day_plans?: DayPlan[]; budget?: Budget }
```

- [ ] **Step 2: 扩展 store**

修改 `frontend/src/stores/trip.ts`：

2a. 顶部 import 加 `Budget`：

```ts
import type { ClarifyPayload, DayPlan, Budget } from '../types'
```

2b. 在 `const clarifyPending = ...` 行后新增：

```ts
  const budget = ref<Budget | null>(null)
```

2c. 在 `const setActivePoi = ...` 行后追加 `setBudget`（`setDayPlans` 保持不动，budget 由 `setBudget` 独立管理）：

```ts
  const setBudget = (b: Budget | null) => { budget.value = b }
```

2d. 在 `return { ... }` 暴露 `budget` 与 `setBudget`：

```ts
  return {
    messages, agentProgress, nodeLabels, threadId, dayPlans, clarifyPending,
    activeDay, activePoiId, budget,
    addMessage, appendToLastMessage, startNode, endNode, clearProgress,
    setThreadId, setClarify, clearClarify, setDayPlans, setActiveDay, setActivePoi, setBudget,
  }
```

- [ ] **Step 3: useSSE final 分支写 budget**

修改 `frontend/src/composables/useSSE.ts` 的 `case 'final':` 分支：

```ts
          case 'final':
            tripStore.setDayPlans((data as FinalPayload).day_plans || [])
            loading.value = false
            break
```

改为：

```ts
          case 'final':
            tripStore.setDayPlans((data as FinalPayload).day_plans || [])
            tripStore.setBudget((data as FinalPayload).budget ?? null)
            loading.value = false
            break
```

- [ ] **Step 4: 进度条标签**

修改 `frontend/src/components/AgentProgress.vue` 的 `LABELS` 对象，把：

```ts
  itinerary: '编排行程', summarize: '生成攻略',
```

改为：

```ts
  itinerary: '编排行程', accommodation: '挑选住宿', budget: '核算预算', summarize: '生成攻略',
```

- [ ] **Step 5: 类型检查通过**

Run: `cd frontend && bun run build`
Expected: 构建成功，无 TS 报错（`FinalPayload.budget`、`DayPlan.hotel`、`TripItem.cost` 已声明；store `setBudget` 已暴露）。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/stores/trip.ts frontend/src/composables/useSSE.ts frontend/src/components/AgentProgress.vue
git commit -m "feat(m4): 前端预算/酒店类型 + store budget 状态 + final 写入 + 进度标签" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: ResultPanel 预算总览条 + 每日酒店卡

**Files:**
- Modify: `frontend/src/components/ResultPanel.vue`

**Interfaces:**
- Consumes: `tripStore.budget`（Task 6）、`currentDay.hotel`（`DayPlan.hotel`）。
- Produces: 面板顶部预算总览条（总额/预算/明细/超支提示）；每天时间线末尾酒店卡。

- [ ] **Step 1: 整体替换 ResultPanel.vue**

整体替换 `frontend/src/components/ResultPanel.vue`：

```vue
<template>
  <div class="result-panel" :class="{ collapsed }">
    <button class="toggle-btn" @click="collapsed = !collapsed">
      {{ collapsed ? '行程 «' : '» 收起' }}
    </button>

    <div v-show="!collapsed" class="panel-body">
      <div v-if="tripStore.dayPlans.length === 0" class="empty">
        <p>行程生成后显示在这里</p>
      </div>

      <template v-else>
        <div v-if="tripStore.budget" class="budget-bar" :class="{ over: tripStore.budget.over }">
          <div class="budget-head">
            <span class="budget-total">已估 ¥{{ tripStore.budget.estimated }}</span>
            <span v-if="tripStore.budget.limit > 0" class="budget-limit">
              / 预算 ¥{{ tripStore.budget.limit }}
            </span>
          </div>
          <div v-if="tripStore.budget.over" class="budget-warn">
            ⚠ 超支 ¥{{ Math.round(tripStore.budget.estimated - tripStore.budget.limit) }}
            （已自动重排 {{ tripStore.budget.retry_count }} 次）
          </div>
          <div v-if="tripStore.budget.note" class="budget-note">{{ tripStore.budget.note }}</div>
          <div class="budget-breakdown">
            <span>门票 ¥{{ tripStore.budget.breakdown.ticket }}</span>
            <span>住宿 ¥{{ tripStore.budget.breakdown.hotel }}</span>
            <span>餐饮 ¥{{ tripStore.budget.breakdown.food }}</span>
            <span>交通 ¥{{ tripStore.budget.breakdown.transport }}</span>
          </div>
        </div>

        <div class="day-tabs">
          <button
            v-for="dp in tripStore.dayPlans"
            :key="dp.day"
            class="day-tab"
            :class="{ active: dp.day === tripStore.activeDay }"
            @click="tripStore.setActiveDay(dp.day)"
          >
            Day {{ dp.day }}
          </button>
        </div>

        <div v-if="currentDay" class="day-meta">
          <span>{{ currentDay.weather.text }}</span>
          <span v-if="currentDay.weather.temp"> · {{ currentDay.weather.temp }}</span>
        </div>

        <div class="timeline">
          <div
            v-for="item in currentDay?.items || []"
            :key="item.poi_id"
            :ref="(el) => setItemRef(item.poi_id, el)"
            class="trip-card"
            :class="{ active: item.poi_id === tripStore.activePoiId }"
            @click="tripStore.setActivePoi(item.poi_id)"
          >
            <span class="card-icon">{{ item.type === 'meal' ? '🍴' : '📍' }}</span>
            <div class="card-text">
              <div class="card-name">{{ item.name }}</div>
              <div class="card-sub">
                <span v-if="item.type === 'attraction' && item.indoor" class="card-tag">室内</span>
                <span v-if="item.cost" class="card-cost">¥{{ item.cost }}/人</span>
              </div>
            </div>
          </div>

          <div v-if="currentDay?.hotel" class="trip-card hotel-card">
            <span class="card-icon">🏨</span>
            <div class="card-text">
              <div class="card-name">{{ currentDay.hotel.name }}</div>
              <div class="card-sub">
                <span v-if="currentDay.hotel.level" class="card-tag hotel-tag">{{ currentDay.hotel.level }}</span>
                <span class="card-cost">¥{{ currentDay.hotel.price }}/晚</span>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { useTripStore } from '../stores/trip'

const tripStore = useTripStore()
const collapsed = ref(false)

const currentDay = computed(() =>
  tripStore.dayPlans.find((d) => d.day === tripStore.activeDay) || null,
)

const itemRefs = new Map<string, HTMLElement>()
const setItemRef = (poiId: string, el: unknown) => {
  if (el) itemRefs.set(poiId, el as HTMLElement)
  else itemRefs.delete(poiId)
}

// activePoiId 命中当前面板的卡片 → 滚动可见
watch(
  () => tripStore.activePoiId,
  async (id) => {
    if (!id) return
    await nextTick()
    itemRefs.get(id)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  },
)
</script>

<style scoped>
.result-panel {
  position: absolute;
  top: 16px;
  right: 16px;
  bottom: 16px;
  width: 300px;
  background: rgba(255, 255, 255, 0.96);
  border-radius: 12px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.12);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width 0.2s ease;
}
.result-panel.collapsed {
  width: auto;
}
.toggle-btn {
  flex-shrink: 0;
  border: none;
  background: #f4f4f5;
  color: #606266;
  font-size: 12px;
  padding: 8px 12px;
  cursor: pointer;
  text-align: right;
}
.toggle-btn:hover { background: #ecf5ff; color: #409eff; }
.panel-body { flex: 1; overflow-y: auto; padding: 8px 12px 12px; }
.empty { color: #909399; font-size: 13px; text-align: center; padding: 24px 0; }

.budget-bar {
  background: #f4f9f0;
  border: 1px solid #e1f3d8;
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 10px;
}
.budget-bar.over { background: #fef0f0; border-color: #fde2e2; }
.budget-head { font-size: 14px; font-weight: 600; color: #303133; }
.budget-limit { color: #909399; font-weight: 400; font-size: 12px; }
.budget-warn { margin-top: 4px; font-size: 12px; color: #f56c6c; font-weight: 600; }
.budget-note { margin-top: 4px; font-size: 12px; color: #e6a23c; }
.budget-breakdown {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  margin-top: 6px;
  font-size: 11px;
  color: #606266;
}

.day-tabs { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.day-tab {
  border: 1px solid #dcdfe6;
  background: #fff;
  color: #606266;
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
}
.day-tab.active { background: #409eff; color: #fff; border-color: #409eff; }
.day-meta { font-size: 12px; color: #909399; margin-bottom: 8px; }
.timeline { display: flex; flex-direction: column; gap: 8px; }
.trip-card {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.trip-card:hover { border-color: #c6e2ff; }
.trip-card.active {
  border-color: #409eff;
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.2);
}
.hotel-card { cursor: default; background: #fafcff; border-color: #e6eefb; }
.hotel-card:hover { border-color: #e6eefb; }
.card-icon { font-size: 16px; line-height: 1.4; }
.card-text { flex: 1; min-width: 0; }
.card-name { font-size: 14px; color: #303133; font-weight: 500; }
.card-sub { display: flex; align-items: center; gap: 6px; margin-top: 4px; }
.card-tag {
  display: inline-block;
  font-size: 11px;
  color: #67c23a;
  background: #f0f9eb;
  border-radius: 4px;
  padding: 1px 6px;
}
.hotel-tag { color: #409eff; background: #ecf5ff; }
.card-cost { font-size: 12px; color: #e6a23c; font-weight: 600; }
</style>
```

- [ ] **Step 2: 类型检查通过**

Run: `cd frontend && bun run build`
Expected: 构建成功。`Math` 在模板中可直接用；`currentDay?.hotel` 与 `item.cost` 均已在类型中声明。

- [ ] **Step 3: 手动验收**

`cd frontend && bun run dev`，后端已起、配好 Key 后发起带预算的完整规划。
Expected:
- 面板顶部出现预算总览条：已估 ¥X / 预算 ¥Y + 门票/住宿/餐饮/交通明细。
- 每天时间线末尾出现 🏨 酒店卡（名称 + 档位 + ¥/晚）；末日无酒店卡。
- 行程项卡片显示 ¥X/人（cost 为 0 时不显示）。
- 超支场景总览条变红 + "⚠ 超支 …（已自动重排 N 次）"。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ResultPanel.vue
git commit -m "feat(m4): ResultPanel 预算总览条 + 超支提示 + 每日酒店卡 + 单项费用" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: M4 验收清单文档 + 全链路验收

**Files:**
- Modify: `backend/README.md`

**Interfaces:**
- Consumes: Task 1–7 的完整闭环。
- Produces: README 增 M4 验收清单；通过后端全量测试 + 前端构建。

- [ ] **Step 1: 全链路自动化校验**

```bash
cd backend && uv run pytest -q
cd ../frontend && bun run build
```
Expected: 后端全绿；前端构建成功。

- [ ] **Step 2: README 增 M4 验收清单**

在 `backend/README.md` 的 `## M3 验收清单` 小节**之后**（`## 测试（M1）` 之前）插入：

````markdown
## M4 验收清单

M4 接通住宿 + 预算闭环：`itinerary → accommodation → budget`，超支条件边回退重排；前端展示预算明细、超支提示与每日酒店。

- 图结构：8 节点 + 2 新节点接线 `itinerary → accommodation → budget ─(over&retry<2)→ itinerary / 否则 → summarize → END`。
- 费用：LLM 估单价（`PlanItem.cost` 人均、`Hotel.price` 每晚整间），`budget` 纯函数汇总；`estimated = num_people × Σ(items.cost) + Σ(hotel.price)`。
- 预算口径：`budget` 为总预算（元），`0` 表示不限（不回退）。
- 超支回退：`budget` 算超支额 + 挑「最贵可削减项」入 `budget_advice`，`itinerary` 据此 LLM 重排；`retry_count ≤ 2` 封顶，到顶带「已尽力压缩」说明。
- `final` 事件 data：`{answer, day_plans, budget}`，`day_plans[i].hotel` 嵌入当晚住宿（末日为 null）。

### 多轮 + 预算流验证（curl）

```bash
curl -N -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
  -d '{"message":"成都3天2人，爱吃辣，预算4000"}'
```

**期望**（缺口齐备后）：`node_start` 依次经 dispatch → 并行检索 → itinerary → **accommodation → budget** → summarize；`token` 逐字流出；`event: final` 的 data 含 `budget`（limit/estimated/over/breakdown）与 `day_plans`（每天含 `hotel`、每项含 `cost`）。超支（如把预算改小到 1500）时可见 itinerary/accommodation/budget 重跑一轮，final 的 `budget.over=true` 且带 `note`。

### 端到端验收（前端）

在 backend 已启动、前端已填 `VITE_AMAP_JS_KEY` 前提下走完对话流：

1. **预算总览**：final 后右侧面板顶部出现「已估 ¥X / 预算 ¥Y」+ 门票/住宿/餐饮/交通明细。
2. **每日酒店**：每天时间线末尾出现 🏨 酒店卡（名称 + 档位 + ¥/晚）；末日无酒店卡。
3. **单项费用**：行程项卡片显示 ¥X/人（cost 为 0 时不显示）。
4. **超支提示**：输入偏紧预算（如 1500）→ 总览条变红 + 「⚠ 超支 …（已自动重排 N 次）」，或封顶显示「已尽力压缩」。
5. **不限预算**：不填预算 → 总览条只显示已估总额，无超支提示，不回退。
6. **✅ 验收**：完整 7 步编排跑通；预算明细、每日酒店、超支自动重排均通过。

### 测试（M4）

```bash
cd backend && uv run pytest -q
```

**关键测试覆盖**：
- `test_budget.py`：纯函数核算（分类汇总、不限、超支回退、retry 封顶、路由）。
- `test_accommodation.py`：过夜日分配、档位关键词、嵌入合并、单日无住宿、POI 空降级。
- `test_itinerary.py`：`PlanItem.cost`/`Hotel`/`DayPlan.hotel`、回退建议入 payload。
- `test_builder.py`：图含 accommodation/budget 节点 + 超支条件边（两去向）。
- `test_chat_stream_m4.py`：端到端 final 携 budget + 酒店/费用；超支触发回退并封顶。
````

并把 `## M2 验收清单` 小节内那行：

```markdown
- `accommodation`/`budget` 仍占位（M4）。
```

改为：

```markdown
- `accommodation`/`budget` 在 M4 接通（见下「M4 验收清单」）。
```

- [ ] **Step 3: 端到端手动验收（配真实 Key）**

按上面 README「端到端验收（前端）」6 步走一遍，确认全部通过。

- [ ] **Step 4: Commit**

```bash
git add backend/README.md
git commit -m "docs(m4): backend README 增 M4 验收清单（住宿+预算闭环手动验收路径）" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## 任务依赖

Task 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 线性依赖（后者消费前者的接口/契约）。建议顺序执行：

- 后端：Task 1（itinerary 契约）→ 2（budget 纯函数）→ 3（accommodation，依赖 Task 1 的 Hotel）→ 4（接线，依赖 2/3）→ 5（stream + 端到端）。
- 前端：Task 6（数据层）→ 7（UI）。
- 收尾：Task 8（文档 + 全链路验收）。
