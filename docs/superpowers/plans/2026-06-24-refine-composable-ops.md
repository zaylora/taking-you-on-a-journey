# refine 可组合原子操作 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 refine 路径的「关键词/正则解析 + 9 值封闭 op」换成「LLM 语义理解产出可组合原子操作序列 + 确定性执行器」，使各种修改请求（尤其「把第一天改成黄埔」这类换区域）被统一接住。

**Architecture:** dispatch_agent 在 refine 分支调一次 LLM 结构化输出，产出 `RefinePlan{operations, clarification}`；refine 节点在 day_plans 工作副本上按序应用 8 个正交原语，尽力而为、诚实回报；routing 改读派生标志而非单一 op。

**Tech Stack:** Python 3.13 + LangGraph + LangChain ChatModel（`build_llm(...).with_structured_output(method="function_calling")`）+ pydantic v2 + 高德 amap 工具 + pytest（`asyncio_mode=auto`）。

## Global Constraints

- 所有节点 LLM 调用统一走 `app.llm.factory.build_llm(temperature=0).with_structured_output(Schema, method="function_calling")`（与 dispatch_agent 现有 `NormalizedReq`/`IntentResult` 一致）。
- `refine_request` 只允许被 `dispatch_agent`（产）/ `refine`（消）/ `routing`（读标志）三处读写；`/api/plan/refine` 是空壳，不改。
- 依赖优先原则（项目 CLAUDE.md）：复用现有 `app/itinerary/geometry.py`（`build_day_stops`/`insert_transport`/`haversine_km`）、`app/tools/amap.py`（`geocode`/`search_around`）、`app/core/constants.AROUND_RADIUS_M`，**不引新依赖、不手写已有能力**。
- 高德 Key 绝不进日志/SSE/前端（沿用 amap 现状，无需额外处理）。
- 代码与用户可见文案用简体中文；注释风格与既有节点一致。
- 测试一律从 `backend/` 目录用 `uv run pytest` 跑；不依赖真实网络/Key（用 `make_fake_build_llm` 与 `fake_amap`）。
- 派生标志确定性：`needs_budget_recheck = 任一 op != "reorder"`；`needs_accommodation = 任一 op == "set_hotel"`；`plan_version` 仅当有结构变化（`changed` 非空）才 +1。

---

### Task 1: 原子操作 schema（refine_ops.py）

**Files:**
- Create: `backend/app/graph/nodes/refine_ops.py`
- Test: `backend/tests/test_refine_ops_schema.py`

**Interfaces:**
- Produces:
  - `class Selector(BaseModel)`：`by: Literal["name","ordinal"]="name"`, `name: str=""`, `kind: Literal["attraction","meal"]="attraction"`, `index: int=-1`
  - `class Operation(BaseModel)`：`op: Literal[...8...]`, `day: int|None=None`, `area: str=""`, `query: str=""`, `kind: Literal["attraction","meal"]="attraction"`, `selector: Selector|None=None`, `strategy: Literal["optimize","reverse"]="optimize"`, `direction: Literal["relax","tighten"]="relax"`, `amount: float|None=None`, `days: list[int]|None=None`, `criteria: str=""`
  - `class RefinePlan(BaseModel)`：`operations: list[Operation]=[]`, `clarification: str|None=None`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_refine_ops_schema.py`：
```python
import pytest
from pydantic import ValidationError

from app.graph.nodes.refine_ops import Operation, Selector, RefinePlan


def test_operation_minimal_defaults():
    op = Operation(op="reorder", day=1)
    assert op.op == "reorder" and op.day == 1
    assert op.strategy == "optimize" and op.direction == "relax"
    assert op.selector is None and op.amount is None


def test_selector_defaults():
    s = Selector(by="ordinal", kind="meal", index=0)
    assert s.by == "ordinal" and s.kind == "meal" and s.index == 0
    assert Selector().by == "name" and Selector().index == -1


def test_refine_plan_parses_mixed_ops_from_dict():
    plan = RefinePlan(**{
        "operations": [
            {"op": "set_region", "day": 1, "area": "黄埔"},
            {"op": "set_pace", "day": 1, "direction": "relax"},
            {"op": "remove_poi", "day": 2, "selector": {"by": "name", "name": "武侯祠"}},
        ],
        "clarification": None,
    })
    assert [o.op for o in plan.operations] == ["set_region", "set_pace", "remove_poi"]
    assert plan.operations[0].area == "黄埔"
    assert plan.operations[2].selector.name == "武侯祠"


def test_refine_plan_empty_with_clarification():
    plan = RefinePlan(operations=[], clarification="你想把第几天换到哪里？")
    assert plan.operations == [] and plan.clarification.startswith("你想")


def test_unknown_op_rejected():
    with pytest.raises(ValidationError):
        Operation(op="teleport", day=1)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_refine_ops_schema.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.graph.nodes.refine_ops'`）

- [ ] **Step 3: 写实现**

`backend/app/graph/nodes/refine_ops.py`：
```python
"""refine 可组合原子操作的结构化 schema（LLM 解析产出 → state['refine_request']）。

扁平 Operation 模型：所有字段可选 + op 字面量。执行器侧按 op 校验必填字段，
缺失即视为该 op 解析失败并跳过（见 refine 节点）。选用扁平模型而非 discriminated
union，是因为跨 provider 的 function-calling 对联合类型支持不稳。
"""
from typing import Literal

from pydantic import BaseModel, Field


class Selector(BaseModel):
    """remove_poi / replace_poi 的目标项定位器。"""
    by: Literal["name", "ordinal"] = "name"
    name: str = Field(default="", description="按名字模糊匹配（item.name 包含该串）")
    kind: Literal["attraction", "meal"] = Field(default="attraction", description="按序号定位时的项类型")
    index: int = Field(default=-1, description="按序号定位：同类项中的序号，-1 表示最后一个")


class Operation(BaseModel):
    op: Literal[
        "set_region", "add_poi", "remove_poi", "replace_poi",
        "reorder", "set_pace", "set_budget", "set_hotel",
    ]
    day: int | None = Field(default=None, description="目标天（从 1 开始）；全局操作可为空")
    area: str = Field(default="", description="set_region：新区域地名，如「黄埔」")
    query: str = Field(default="", description="add_poi/replace_poi/set_region：检索关键词")
    kind: Literal["attraction", "meal"] = Field(default="attraction", description="add_poi/replace_poi：新增/替换的项类型")
    selector: Selector | None = Field(default=None, description="remove_poi/replace_poi：要操作的目标项")
    strategy: Literal["optimize", "reverse"] = Field(default="optimize", description="reorder：optimize=就近重排，reverse=倒序")
    direction: Literal["relax", "tighten"] = Field(default="relax", description="set_pace：relax/tighten 均做删减至时间预算内")
    amount: float | None = Field(default=None, description="set_budget：新预算上限(元)")
    days: list[int] | None = Field(default=None, description="set_hotel：目标过夜日；空=全部过夜日")
    criteria: str = Field(default="", description="set_hotel：偏好描述，如「离地铁近」")


class RefinePlan(BaseModel):
    operations: list[Operation] = Field(default_factory=list, description="按用户语序排列的原子操作")
    clarification: str | None = Field(default=None, description="无法解析出任何操作时，向用户反问的一句话")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_refine_ops_schema.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/refine_ops.py backend/tests/test_refine_ops_schema.py
git commit -m "feat(m6-v2): refine 原子操作 schema（Operation/Selector/RefinePlan）"
```

---

### Task 2: 纯函数 helper — selector 解析 + center 重算 + 就近重排 + 删减

**Files:**
- Modify: `backend/app/graph/nodes/refine.py`（新增 helper，暂不动 `refine()`）
- Test: `backend/tests/test_refine_helpers.py`

**Interfaces:**
- Consumes（既有，来自 itinerary 再导出）：`insert_transport`, `build_day_stops`, `haversine_km`；`time_budget.day_used_minutes`, `time_budget.DAY_BUDGET`
- Produces：
  - `_resolve_selector(items: list[dict], selector: dict | None) -> int | None`
  - `_recompute_center(stops: list[dict]) -> dict`（`{"lng":float,"lat":float}`）
  - `_optimize_stops(stops: list[dict]) -> list[dict]`
  - `_relax_stops(stops: list[dict]) -> list[dict]`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_refine_helpers.py`：
```python
from app.graph.nodes.refine import (
    _resolve_selector, _recompute_center, _optimize_stops, _relax_stops,
)


def _stops():
    return [
        {"type": "attraction", "name": "武侯祠", "poi_id": "A1", "location": {"lng": 104.05, "lat": 30.65}},
        {"type": "meal", "name": "陈麻婆", "poi_id": "M1", "location": {"lng": 104.06, "lat": 30.66}},
        {"type": "attraction", "name": "锦里", "poi_id": "A2", "location": {"lng": 104.04, "lat": 30.64}},
    ]


def test_resolve_selector_by_name():
    assert _resolve_selector(_stops(), {"by": "name", "name": "锦里"}) == 2
    assert _resolve_selector(_stops(), {"by": "name", "name": "不存在"}) is None


def test_resolve_selector_by_ordinal_last_attraction():
    # 最后一个 attraction 是「锦里」(index 2)
    assert _resolve_selector(_stops(), {"by": "ordinal", "kind": "attraction", "index": -1}) == 2
    # 第一个 meal 是「陈麻婆」(index 1)
    assert _resolve_selector(_stops(), {"by": "ordinal", "kind": "meal", "index": 0}) == 1


def test_resolve_selector_out_of_range_returns_none():
    assert _resolve_selector(_stops(), {"by": "ordinal", "kind": "meal", "index": 5}) is None


def test_recompute_center_is_mean_of_stop_coords():
    c = _recompute_center(_stops())
    assert round(c["lng"], 3) == round((104.05 + 104.06 + 104.04) / 3, 3)
    assert round(c["lat"], 3) == round((30.65 + 30.66 + 30.64) / 3, 3)


def test_recompute_center_empty():
    assert _recompute_center([]) == {"lng": 0.0, "lat": 0.0}


def test_optimize_stops_starts_from_first_and_is_permutation():
    out = _optimize_stops(_stops())
    assert out[0]["poi_id"] == "A1"
    assert sorted(s["poi_id"] for s in out) == ["A1", "A2", "M1"]


def test_relax_stops_removes_at_least_one_when_over_budget():
    # 6 个景点（无 visit_minutes 时按默认估时）必定超 DAY_BUDGET → 至少删 1
    big = [{"type": "attraction", "name": f"P{i}", "poi_id": f"A{i}",
            "location": {"lng": 104.0 + i * 0.01, "lat": 30.6}} for i in range(6)]
    out = _relax_stops(big)
    assert len(out) < len(big)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_refine_helpers.py -q`
Expected: FAIL（`ImportError: cannot import name '_resolve_selector'`）

- [ ] **Step 3: 写实现**

在 `backend/app/graph/nodes/refine.py` 顶部 import 区补充（与现有 import 合并）：
```python
from app.graph.nodes.itinerary import insert_transport, build_day_stops, haversine_km
from app.graph.nodes.time_budget import attraction_minutes, day_used_minutes, DAY_BUDGET
from app.core.constants import AROUND_RADIUS_M
from app.tools import amap
```
在文件中新增以下纯函数（放在 `_find_day` 附近）：
```python
def _resolve_selector(items: list[dict], selector: dict | None) -> int | None:
    """按 selector 在 items 里定位一个停靠点的下标；命不中返回 None。"""
    sel = selector or {}
    if sel.get("by", "name") == "name":
        name = (sel.get("name") or "").strip()
        if not name:
            return None
        for i, it in enumerate(items):
            if it.get("type") != "transport" and name in (it.get("name") or ""):
                return i
        return None
    kind = sel.get("kind", "attraction")
    idxs = [i for i, it in enumerate(items) if it.get("type") == kind]
    if not idxs:
        return None
    try:
        return idxs[sel.get("index", -1)]
    except IndexError:
        return None


def _recompute_center(stops: list[dict]) -> dict:
    """当天 center = 非交通停靠点坐标均值。"""
    pts = [it.get("location") or {} for it in stops if it.get("type") != "transport"]
    pts = [p for p in pts if p]
    if not pts:
        return {"lng": 0.0, "lat": 0.0}
    return {"lng": sum(p.get("lng", 0.0) for p in pts) / len(pts),
            "lat": sum(p.get("lat", 0.0) for p in pts) / len(pts)}


def _optimize_stops(stops: list[dict]) -> list[dict]:
    """从首个停靠点起，贪心最近邻重排（按 location 直线距离）。"""
    if len(stops) < 3:
        return list(stops)
    remaining = list(stops)
    order = [remaining.pop(0)]
    while remaining:
        last = order[-1].get("location") or {}
        j = min(range(len(remaining)),
                key=lambda i: haversine_km(remaining[i].get("location") or {}, last))
        order.append(remaining.pop(j))
    return order


def _relax_stops(stops: list[dict]) -> list[dict]:
    """反复删当天最后一个景点/餐饮，直到 day_used_minutes <= DAY_BUDGET（至少删 1 个）。"""
    items = list(stops)
    removed = False
    while items and (day_used_minutes(insert_transport(items)) > DAY_BUDGET or not removed):
        removable = [i for i, it in enumerate(items)
                     if it.get("type") in ("attraction", "meal") and it.get("name")]
        if not removable:
            break
        items.pop(removable[-1])
        removed = True
        if day_used_minutes(insert_transport(items)) <= DAY_BUDGET:
            break
    return items
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_refine_helpers.py -q`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/refine.py backend/tests/test_refine_helpers.py
git commit -m "feat(m6-v2): refine 纯函数 helper（selector/center/optimize/relax）"
```

---

### Task 3: 执行器重写（序列循环 + 无检索 handler + 派生标志 + 诚实回报）

**Files:**
- Modify: `backend/app/graph/nodes/refine.py`（重写 `refine()`，新增 `_apply_day_op`/`_finalize_day`；删除旧 `_infer_op`/`_relax_until_budget`/`_relax_day`/`_reorder_day`/`_rebuild_transport`/`_set_meal`/`_add_or_replace_attraction`/`_apply_search_op`）
- Test: `backend/tests/test_refine_node.py`（重写为 operations 形状）

**Interfaces:**
- Consumes：Task 2 的 helper；既有 `_find_day`, `_poi_to_item`, `_overnight_days`
- Produces：
  - `async def refine(state, config=None) -> dict`，返回 `{day_plans, refine_request(含 needs_budget_recheck/needs_accommodation), changed_days, plan_version, refine_notes, [budget]}`
  - `async def _apply_day_op(state, day_plan: dict, op: dict) -> tuple[dict, bool, str]`（本任务只接 `reorder`/`set_pace`/`remove_poi`；`add_poi`/`replace_poi`/`set_region` 在 Task 4/5 接上，未接的 op 先走「未知操作」分支）
  - `def _finalize_day(day_plan: dict) -> dict`（`items=insert_transport(stops)` + `center=_recompute_center(stops)`）

- [ ] **Step 1: 写失败测试（重写 test_refine_node.py 全文）**

`backend/tests/test_refine_node.py`：
```python
from app.graph.nodes.refine import refine, _find_day, _finalize_day
from app.graph.nodes.itinerary import insert_transport


def _plan():
    day1 = [
        {"type": "attraction", "name": "武侯祠", "poi_id": "B1", "location": {"lng": 104.05, "lat": 30.65}},
        {"type": "meal", "name": "陈麻婆", "poi_id": "M1", "location": {"lng": 104.06, "lat": 30.66}},
    ]
    day2 = [
        {"type": "attraction", "name": "杜甫草堂", "poi_id": "B2", "location": {"lng": 104.04, "lat": 30.67}},
        {"type": "attraction", "name": "金沙遗址", "poi_id": "B3", "location": {"lng": 104.03, "lat": 30.68}},
    ]
    return [
        {"day": 1, "items": insert_transport(day1), "center": {"lng": 104.055, "lat": 30.655}},
        {"day": 2, "items": insert_transport(day2), "center": {"lng": 104.035, "lat": 30.675}},
    ]


def test_find_day():
    assert _find_day(_plan(), 2) == 1
    assert _find_day(_plan(), 9) is None


def test_finalize_day_inserts_transport_and_center():
    dp = _finalize_day({"day": 1, "items": [
        {"type": "attraction", "name": "A", "location": {"lng": 104.0, "lat": 30.0}},
        {"type": "attraction", "name": "B", "location": {"lng": 104.02, "lat": 30.0}},
    ]})
    assert [i["type"] for i in dp["items"]] == ["attraction", "transport", "attraction"]
    assert round(dp["center"]["lng"], 3) == 104.01


async def test_reorder_reverse_only_target_day():
    state = {"day_plans": _plan(), "plan_version": 1,
             "refine_request": {"operations": [{"op": "reorder", "day": 1, "strategy": "reverse"}]}}
    out = await refine(state)
    assert out["changed_days"] == [1]
    stops = [i for i in out["day_plans"][0]["items"] if i.get("type") != "transport"]
    assert [i["name"] for i in stops] == ["陈麻婆", "武侯祠"]
    assert out["day_plans"][1]["items"] == _plan()[1]["items"]   # 第二天不动
    assert out["refine_request"]["needs_budget_recheck"] is False  # 纯 reorder 不重算预算


async def test_set_pace_relax_removes_and_recheck_budget():
    state = {"day_plans": _plan(), "plan_version": 1,
             "refine_request": {"operations": [{"op": "set_pace", "day": 2, "direction": "relax"}]}}
    out = await refine(state)
    assert out["changed_days"] == [2]
    assert len(out["day_plans"][1]["items"]) == 1   # 2 景点删 1 → 1 停靠点（<2 不插交通）
    assert out["plan_version"] == 2
    assert out["refine_request"]["needs_budget_recheck"] is True


async def test_remove_poi_by_name():
    state = {"day_plans": _plan(), "plan_version": 1,
             "refine_request": {"operations": [
                 {"op": "remove_poi", "day": 1, "selector": {"by": "name", "name": "武侯祠"}}]}}
    out = await refine(state)
    stops = [i["name"] for i in out["day_plans"][0]["items"] if i.get("type") != "transport"]
    assert "武侯祠" not in stops and "陈麻婆" in stops
    assert out["changed_days"] == [1]


async def test_remove_poi_miss_is_skipped_not_destructive():
    state = {"day_plans": _plan(), "plan_version": 1,
             "refine_request": {"operations": [
                 {"op": "remove_poi", "day": 1, "selector": {"by": "name", "name": "不存在景点"}}]}}
    out = await refine(state)
    assert out["changed_days"] == []
    assert out["day_plans"] == _plan()                       # 行程一字未动
    assert out["plan_version"] == 1                           # 无结构变化不增版本
    assert out["refine_notes"]["skipped"]                     # 有跳过记录
    assert not out["refine_notes"]["applied"]


async def test_set_budget_updates_limit_without_touching_plan():
    state = {"day_plans": _plan(), "plan_version": 1, "budget": 5000,
             "refine_request": {"operations": [{"op": "set_budget", "amount": 3000.0}]}}
    out = await refine(state)
    assert out["budget"] == 3000.0
    assert out["changed_days"] == [] and out["day_plans"] == _plan()
    assert out["plan_version"] == 1
    assert out["refine_request"]["needs_budget_recheck"] is True


async def test_set_hotel_marks_overnight_and_flags_accommodation():
    state = {"day_plans": _plan(), "plan_version": 1,
             "refine_request": {"operations": [{"op": "set_hotel", "criteria": "离地铁近"}]}}
    out = await refine(state)
    assert out["changed_days"] == [1]                         # 过夜日（共 2 天 → 第 1 天过夜）
    assert out["day_plans"][0]["items"] == _plan()[0]["items"]  # items 不动
    assert out["refine_request"]["needs_accommodation"] is True
    assert out["plan_version"] == 2


async def test_compound_reorder_then_remove_applied_in_order():
    state = {"day_plans": _plan(), "plan_version": 1,
             "refine_request": {"operations": [
                 {"op": "reorder", "day": 2, "strategy": "reverse"},
                 {"op": "remove_poi", "day": 2, "selector": {"by": "ordinal", "kind": "attraction", "index": -1}}]}}
    out = await refine(state)
    # reverse: [金沙, 杜甫] → 删最后一个 attraction(杜甫) → 剩 [金沙]
    stops = [i["name"] for i in out["day_plans"][1]["items"] if i.get("type") != "transport"]
    assert stops == ["金沙遗址"]
    assert out["changed_days"] == [2]
    assert len(out["refine_notes"]["applied"]) == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_refine_node.py -q`
Expected: FAIL（旧 `refine()` 读 `refine_request["op"]`，新测试传 `operations` → 断言不符 / `_finalize_day` 未定义）

- [ ] **Step 3: 写实现（重写 refine.py 的节点部分）**

把 `backend/app/graph/nodes/refine.py` 里旧的 `_infer_op`、`_relax_day`、`_relax_until_budget`、`_reorder_day`、`_set_meal`、`_add_or_replace_attraction`、`_apply_search_op`、`_rebuild_transport` 以及旧 `async def refine(...)` **整体删除**，替换为下列内容（保留 `_find_day`、`_poi_to_item`、`_overnight_days`、Task 2 的四个 helper）：
```python
def _finalize_day(day_plan: dict) -> dict:
    """收尾：剥掉旧交通段、按当前停靠点重插交通、重算 center。"""
    dp = dict(day_plan)
    stops = [it for it in (dp.get("items") or []) if it.get("type") != "transport"]
    dp["items"] = insert_transport(stops)
    dp["center"] = _recompute_center(stops)
    return dp


async def _apply_day_op(state, day_plan: dict, op: dict) -> tuple[dict, bool, str]:
    """对单天应用一个 op。返回 (更新后的 day_plan(items 为停靠点，未插交通), ok, note)。

    Task 3 接入：reorder / set_pace / remove_poi。
    Task 4 接入：add_poi / replace_poi。Task 5 接入：set_region。
    """
    kind = op.get("op")
    dp = dict(day_plan)
    stops = [it for it in (dp.get("items") or []) if it.get("type") != "transport"]
    day = dp.get("day")

    if kind == "reorder":
        strat = op.get("strategy", "optimize")
        dp["items"] = list(reversed(stops)) if strat == "reverse" else _optimize_stops(stops)
        return dp, True, f"第{day}天顺序已调整"

    if kind == "set_pace":
        new_stops = _relax_stops(stops)
        dp["items"] = new_stops
        if len(new_stops) == len(stops):
            return dp, False, f"第{day}天已无可删减项"
        return dp, True, f"第{day}天已精简{len(stops) - len(new_stops)}项"

    if kind == "remove_poi":
        i = _resolve_selector(stops, op.get("selector"))
        if i is None:
            return dp, False, f"第{day}天未定位到要删除的项"
        removed = stops.pop(i)
        dp["items"] = stops
        return dp, True, f"第{day}天已删除{removed.get('name', '')}"

    return dp, False, f"暂不支持的操作：{kind}"


async def refine(state, config=None) -> dict:
    day_plans = deepcopy(state.get("day_plans", []) or [])
    request = dict(state.get("refine_request", {}) or {})
    operations = list(request.get("operations") or [])
    applied: list[str] = []
    skipped: list[str] = []
    changed: set[int] = set()
    touched: set[int] = set()
    needs_accom = False
    budget_new = None

    for op in operations:
        kind = op.get("op")
        if kind == "set_budget":
            amt = op.get("amount")
            if amt is None:
                skipped.append("预算调整缺少金额，已跳过")
                continue
            budget_new = float(amt)
            applied.append(f"预算改为 {budget_new:.0f}")
            continue
        if kind == "set_hotel":
            days = op.get("days") or _overnight_days(day_plans)
            needs_accom = True
            for d in days:
                changed.add(d)
            applied.append("酒店偏好已更新，将重排住宿")
            continue
        # 按天操作
        day = op.get("day")
        idx = _find_day(day_plans, day)
        if idx is None:
            skipped.append(f"第{day}天未找到，已跳过")
            continue
        dp, ok, note = await _apply_day_op(state, day_plans[idx], op)
        day_plans[idx] = dp
        if ok:
            applied.append(note)
            changed.add(day)
            touched.add(day)
        else:
            skipped.append(note)

    # 每个被结构修改的天：统一重建交通 + 重算 center（一次）
    for d in touched:
        i = _find_day(day_plans, d)
        if i is not None:
            day_plans[i] = _finalize_day(day_plans[i])

    needs_budget = any(o.get("op") != "reorder" for o in operations)
    plan_version = (state.get("plan_version", 0) or 0) + (1 if changed else 0)
    out: dict = {
        "day_plans": day_plans,
        "refine_request": {**request,
                           "needs_budget_recheck": needs_budget,
                           "needs_accommodation": needs_accom},
        "changed_days": sorted(changed),
        "plan_version": plan_version,
        "refine_notes": {"applied": applied, "skipped": skipped},
    }
    if budget_new is not None:
        out["budget"] = budget_new
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_refine_node.py -q`
Expected: PASS（10 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/refine.py backend/tests/test_refine_node.py
git commit -m "feat(m6-v2): refine 执行器重写为序列循环 + 无检索 handler + 诚实回报"
```

---

### Task 4: 检索类 handler（add_poi / replace_poi，围绕当天 center）

**Files:**
- Modify: `backend/app/graph/nodes/refine.py`（在 `_apply_day_op` 接入 `add_poi`/`replace_poi`，新增 `_search_insert`）
- Test: `backend/tests/test_refine_search.py`（重写）

**Interfaces:**
- Consumes：`amap.search_around`（`fake_amap` fixture 可控）；`_poi_to_item`；`AROUND_RADIUS_M`
- Produces：`async def _search_insert(state, dp: dict, stops: list[dict], op: dict, replace_idx: int | None) -> str | None`（成功返回 note，失败/空返回 None；副作用：原地修改 stops）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_refine_search.py`：
```python
from app.graph.nodes.refine import refine
from app.graph.nodes.itinerary import insert_transport


def _plan():
    day1 = [
        {"type": "attraction", "name": "武侯祠", "poi_id": "B1", "location": {"lng": 104.05, "lat": 30.65}},
        {"type": "meal", "name": "陈麻婆", "poi_id": "M1", "location": {"lng": 104.06, "lat": 30.66}},
    ]
    return [{"day": 1, "items": insert_transport(day1), "center": {"lng": 104.05, "lat": 30.65}}]


async def test_add_poi_appends_searched_attraction(fake_amap):
    fake_amap["search_around"] = [
        {"name": "杜甫草堂", "poi_id": "NEW1", "lng": 104.04, "lat": 30.67, "type": "风景名胜"}]
    state = {"day_plans": _plan(), "plan_version": 1, "city": "成都",
             "refine_request": {"operations": [
                 {"op": "add_poi", "day": 1, "query": "草堂", "kind": "attraction"}]}}
    out = await refine(state)
    names = [i["name"] for i in out["day_plans"][0]["items"] if i.get("type") != "transport"]
    assert "杜甫草堂" in names
    assert out["changed_days"] == [1]


async def test_replace_poi_swaps_meal_by_name(fake_amap):
    fake_amap["search_around"] = [
        {"name": "蜀大侠火锅", "poi_id": "HOT1", "lng": 104.06, "lat": 30.66, "type": "餐饮"}]
    state = {"day_plans": _plan(), "plan_version": 1, "city": "成都",
             "refine_request": {"operations": [
                 {"op": "replace_poi", "day": 1, "kind": "meal", "query": "火锅",
                  "selector": {"by": "name", "name": "陈麻婆"}}]}}
    out = await refine(state)
    names = [i["name"] for i in out["day_plans"][0]["items"] if i.get("type") != "transport"]
    assert "蜀大侠火锅" in names and "陈麻婆" not in names


async def test_add_poi_empty_search_is_skipped(fake_amap):
    fake_amap["search_around"] = []   # 检索为空
    state = {"day_plans": _plan(), "plan_version": 1, "city": "成都",
             "refine_request": {"operations": [{"op": "add_poi", "day": 1, "query": "无结果"}]}}
    out = await refine(state)
    assert out["changed_days"] == []
    assert out["day_plans"] == _plan()
    assert out["refine_notes"]["skipped"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_refine_search.py -q`
Expected: FAIL（`add_poi`/`replace_poi` 走「暂不支持」分支 → `changed_days==[]`，断言不符）

- [ ] **Step 3: 写实现**

在 `backend/app/graph/nodes/refine.py` 新增 `_search_insert`，并在 `_apply_day_op` 的 `return dp, False, f"暂不支持..."` 之前插入 `add_poi`/`replace_poi` 两个分支：
```python
async def _search_insert(state, dp: dict, stops: list[dict], op: dict, replace_idx: int | None) -> str | None:
    """围绕当天 center 检索一个 POI 并插入/替换进 stops。空/失败返回 None。"""
    center = dp.get("center") or {}
    kind = op.get("kind", "attraction")
    poi_type = "餐饮" if kind == "meal" else "风景名胜"
    default_kw = "美食" if kind == "meal" else "热门景点"
    try:
        pois = await amap.search_around(center.get("lng", 0.0), center.get("lat", 0.0),
                                        op.get("query") or default_kw, poi_type, AROUND_RADIUS_M)
    except Exception:  # noqa: BLE001 —— 检索失败降级，不阻断本轮
        return None
    if not pois:
        return None
    used = {it.get("poi_id") for it in stops}
    fresh = next((p for p in pois if p.get("poi_id") not in used), pois[0])
    item = _poi_to_item(fresh, "meal" if kind == "meal" else "attraction")
    if replace_idx is None:
        stops.append(item)
        return f"第{dp.get('day')}天新增{item['name']}"
    stops[replace_idx] = item
    return f"第{dp.get('day')}天已替换为{item['name']}"
```
在 `_apply_day_op` 内（`remove_poi` 分支之后、最后的 `return ... 暂不支持` 之前）：
```python
    if kind == "add_poi":
        note = await _search_insert(state, dp, stops, op, replace_idx=None)
        dp["items"] = stops
        return (dp, True, note) if note else (dp, False, f"第{day}天未找到合适候选")

    if kind == "replace_poi":
        i = _resolve_selector(stops, op.get("selector"))
        if i is None:
            return dp, False, f"第{day}天未定位到要替换的项"
        note = await _search_insert(state, dp, stops, op, replace_idx=i)
        dp["items"] = stops
        return (dp, True, note) if note else (dp, False, f"第{day}天未找到替换候选")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_refine_search.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/refine.py backend/tests/test_refine_search.py
git commit -m "feat(m6-v2): refine 接入 add_poi/replace_poi（围绕 center 圆心检索）"
```

---

### Task 5: set_region handler（换区域 → geocode + 重检索 + 重排当天）

**Files:**
- Modify: `backend/app/graph/nodes/refine.py`（在 `_apply_day_op` 接入 `set_region`，新增 `_set_region`）
- Test: `backend/tests/test_refine_region.py`（新增）

**Interfaces:**
- Consumes：`amap.geocode`, `amap.search_around`（`fake_amap` 可控）；`build_day_stops`
- Produces：`async def _set_region(state, dp: dict, op: dict) -> tuple[dict, bool, str]`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_refine_region.py`：
```python
from app.graph.nodes.refine import refine
from app.graph.nodes.itinerary import insert_transport

# 黄埔区参考坐标（经度 > 113.45）
HUANGPU = {"lng": 113.46, "lat": 23.10}


def _gz_plan():
    # 第一天在广州市区（经度约 113.27）
    day1 = [
        {"type": "attraction", "name": "越秀公园", "poi_id": "G1", "location": {"lng": 113.27, "lat": 23.13}},
        {"type": "attraction", "name": "陈家祠", "poi_id": "G2", "location": {"lng": 113.24, "lat": 23.13}},
    ]
    return [{"day": 1, "items": insert_transport(day1), "center": {"lng": 113.276, "lat": 23.1154}}]


async def test_set_region_moves_center_and_researches(fake_amap):
    fake_amap["geocode"] = HUANGPU
    fake_amap["search_around"] = [
        {"name": "黄埔军校旧址", "poi_id": "H1", "lng": 113.47, "lat": 23.09, "type": "风景名胜"},
        {"name": "南海神庙", "poi_id": "H2", "lng": 113.46, "lat": 23.11, "type": "风景名胜"},
    ]
    state = {"day_plans": _gz_plan(), "plan_version": 4, "city": "广州",
             "refine_request": {"operations": [{"op": "set_region", "day": 1, "area": "黄埔"}]}}
    out = await refine(state)
    day1 = out["day_plans"][0]
    # center 迁到黄埔（经度 > 113.45），不再是市区 113.27
    assert day1["center"]["lng"] > 113.45
    # 景点已换成黄埔的新检索结果
    names = [i["name"] for i in day1["items"] if i.get("type") == "attraction"]
    assert "黄埔军校旧址" in names and "越秀公园" not in names
    assert out["changed_days"] == [1]
    assert out["plan_version"] == 5
    assert out["refine_request"]["needs_budget_recheck"] is True


async def test_set_region_geocode_fail_is_skipped(fake_amap):
    fake_amap["geocode"] = {}   # 定位失败
    state = {"day_plans": _gz_plan(), "plan_version": 4, "city": "广州",
             "refine_request": {"operations": [{"op": "set_region", "day": 1, "area": "不存在区"}]}}
    out = await refine(state)
    assert out["changed_days"] == []
    assert out["day_plans"] == _gz_plan()
    assert out["refine_notes"]["skipped"]


async def test_set_region_compound_with_pace(fake_amap):
    fake_amap["geocode"] = HUANGPU
    fake_amap["search_around"] = [
        {"name": f"黄埔景点{i}", "poi_id": f"H{i}", "lng": 113.46 + i * 0.001, "lat": 23.10, "type": "风景名胜"}
        for i in range(5)
    ]
    state = {"day_plans": _gz_plan(), "plan_version": 4, "city": "广州",
             "refine_request": {"operations": [
                 {"op": "set_region", "day": 1, "area": "黄埔"},
                 {"op": "set_pace", "day": 1, "direction": "relax"}]}}
    out = await refine(state)
    assert out["changed_days"] == [1]
    assert len(out["refine_notes"]["applied"]) == 2   # 两步都生效
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_refine_region.py -q`
Expected: FAIL（`set_region` 走「暂不支持」分支）

- [ ] **Step 3: 写实现**

在 `backend/app/graph/nodes/refine.py` 新增 `_set_region`，并在 `_apply_day_op` 末尾「暂不支持」分支之前接入：
```python
async def _set_region(state, dp: dict, op: dict) -> tuple[dict, bool, str]:
    """换区域：geocode 新坐标 → 围绕新 center 检索景点池+餐饮池 → build_day_stops 重排当天。
    沿用原景点数量。center 由 _finalize_day 按新停靠点重算。"""
    area = (op.get("area") or "").strip()
    day = dp.get("day")
    if not area:
        return dp, False, f"第{day}天换区域缺少地名"
    try:
        loc = await amap.geocode(f"{state.get('city', '')}{area}")
    except Exception:  # noqa: BLE001
        loc = {}
    if not loc:
        return dp, False, f"未能定位「{area}」"
    lng, lat = loc.get("lng", 0.0), loc.get("lat", 0.0)
    prev_n = max(1, len([it for it in (dp.get("items") or []) if it.get("type") == "attraction"]))
    food_kw = (state.get("preferences") or {}).get("food") or "美食"
    try:
        attr_pool = await amap.search_around(lng, lat, op.get("query") or "热门景点", "风景名胜", AROUND_RADIUS_M)
        rest_pool = await amap.search_around(lng, lat, food_kw, "餐饮", AROUND_RADIUS_M)
    except Exception:  # noqa: BLE001
        return dp, False, f"「{area}」附近检索失败"
    if not attr_pool:
        return dp, False, f"「{area}」附近未找到景点"
    dp["items"] = build_day_stops(attr_pool[:prev_n], rest_pool or [])
    return dp, True, f"第{day}天已迁至{area}（重排{len(dp['items'])}项）"
```
在 `_apply_day_op` 内（`replace_poi` 分支之后）：
```python
    if kind == "set_region":
        return await _set_region(state, dp, op)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_refine_region.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/refine.py backend/tests/test_refine_region.py
git commit -m "feat(m6-v2): refine 接入 set_region（换区域→geocode→重检索→重排）"
```

---

### Task 6: 解析器改为 LLM 结构化输出（dispatch_agent）

**Files:**
- Modify: `backend/app/graph/nodes/dispatch_agent.py`（删 `_infer_op`/`_parse_refine`/`_refine_flags`；新增 `_day_plans_digest`/`_parse_refine_llm`；改写 refine 分支）
- Test: `backend/tests/test_dispatch_agent.py`（重写受影响用例）

**Interfaces:**
- Consumes：`RefinePlan`（Task 1）；`build_llm`；`conftest.make_fake_build_llm`
- Produces：
  - refine 分支返回 `{"last_intent":"refine_existing", "refine_request":{"operations":[...dict...], "clarification":None}}`
  - 无操作 + 有澄清时返回 `{"last_intent":"qa", "refine_clarification": str}`

- [ ] **Step 1: 写失败测试（重写 test_dispatch_agent.py 受影响部分）**

把 `backend/tests/test_dispatch_agent.py` 中以下三项**删除**：`test_refine_flags_by_op`、`test_parse_refine_extracts_op_day_and_flags`、`test_refine_turn_parses_by_rule_without_llm`（以及顶部 `from ... import _parse_refine, _refine_flags`）。新增/替换为：
```python
import pytest

from app.graph.nodes.dispatch_agent import (
    dispatch_agent, route_after_dispatch, reset_for_plan_new, IntentResult,
)
from app.graph.nodes.dispatch import NormalizedReq
from app.graph.nodes.refine_ops import RefinePlan, Operation
from tests.conftest import make_fake_build_llm


async def test_refine_turn_parses_to_operations_via_llm(monkeypatch):
    plan = RefinePlan(operations=[Operation(op="set_region", day=1, area="黄埔")])
    monkeypatch.setattr("app.graph.nodes.dispatch_agent.build_llm",
                        make_fake_build_llm(structured=plan))
    out = await dispatch_agent(
        {"query": "把第一天改成黄埔", "day_plans": [{"day": 1, "items": []}]}, None)
    assert out["last_intent"] == "refine_existing"
    ops = out["refine_request"]["operations"]
    assert ops[0]["op"] == "set_region" and ops[0]["area"] == "黄埔" and ops[0]["day"] == 1


async def test_refine_no_ops_with_clarification_routes_to_qa(monkeypatch):
    plan = RefinePlan(operations=[], clarification="你想把第几天换到哪里？")
    monkeypatch.setattr("app.graph.nodes.dispatch_agent.build_llm",
                        make_fake_build_llm(structured=plan))
    out = await dispatch_agent(
        {"query": "改一下那个", "day_plans": [{"day": 1, "items": []}]}, None)
    assert out["last_intent"] == "qa"
    assert out["refine_clarification"].startswith("你想")
    assert "refine_request" not in out
```
（保留原有 `test_route_after_dispatch_maps_intent`、`test_reset_for_plan_new_clears_dirty_state`、`test_first_turn_is_plan_new_and_normalizes`、`test_qa_turn_only_sets_intent` 不变。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_dispatch_agent.py -q`
Expected: FAIL（旧 refine 分支用规则解析、不调 `build_llm`，新测试断言 operations 不符；且 `_parse_refine` 已被新测试移除引用）

- [ ] **Step 3: 写实现**

在 `backend/app/graph/nodes/dispatch_agent.py`：删除 `_infer_op`、`_parse_refine`、`_refine_flags` 三个函数；新增 import 与解析函数：
```python
from app.graph.nodes.refine_ops import RefinePlan

_REFINE_SYS = (
    "你是行程修改解析器。把用户对【已有行程】的修改诉求，解析成有序的原子操作列表。"
    "可用操作：set_region(换某天到新区域 area)、add_poi(加景点/餐 query+kind)、"
    "remove_poi(删项 selector)、replace_poi(换项 selector+query+kind)、"
    "reorder(调顺序 strategy)、set_pace(轻松/紧凑 direction)、set_budget(改预算 amount)、"
    "set_hotel(换酒店 criteria)。复合诉求拆成多个操作并按语序排列。"
    "day 必须依据所给 day_plans 判定（从 1 开始）。selector 可按 name 或 ordinal(kind+index,-1=最后)。"
    "若完全无法理解要改什么，operations 留空并在 clarification 用一句中文反问。"
)


def _day_plans_digest(day_plans: list) -> list:
    """压缩 day_plans 给 LLM 看结构（天号 + 各项类型与名称），不下发坐标等噪声。"""
    digest = []
    for d in day_plans or []:
        items = [{"type": it.get("type"), "name": it.get("name", "")}
                 for it in (d.get("items") or []) if it.get("type") != "transport"]
        digest.append({"day": d.get("day"), "items": items})
    return digest


async def _parse_refine_llm(state: dict, query: str, target_day, config) -> RefinePlan:
    llm = build_llm(temperature=0).with_structured_output(RefinePlan, method="function_calling")
    return await llm.ainvoke([
        SystemMessage(content=_REFINE_SYS),
        HumanMessage(content=str({
            "query": query,
            "target_day_hint": target_day,
            "day_plans": _day_plans_digest(state.get("day_plans") or []),
            "city": state.get("city", ""),
            "conversation_summary": state.get("conversation_summary", ""),
        })),
    ], config=config)
```
把 refine 分支（原 `if result.intent == "refine_existing": ...`）替换为：
```python
    if result.intent == "refine_existing":
        plan = await _parse_refine_llm(state, query, result.target_day, config)
        if not plan.operations and plan.clarification:
            return {"last_intent": "qa", "refine_clarification": plan.clarification}
        return {
            "last_intent": "refine_existing",
            "refine_request": {
                "operations": [o.model_dump() for o in plan.operations],
                "clarification": plan.clarification,
            },
        }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_dispatch_agent.py -q`
Expected: PASS（全部用例通过）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/dispatch_agent.py backend/tests/test_dispatch_agent.py
git commit -m "feat(m6-v2): dispatch_agent refine 解析改为 LLM 结构化输出 + 澄清兜底"
```

---

### Task 7: 路由解耦 + 澄清回话 + 诚实回报 + state 字段

**Files:**
- Modify: `backend/app/graph/nodes/routing.py`（`route_after_plan` 读 `needs_accommodation`）
- Modify: `backend/app/graph/nodes/answer.py`（`refine_clarification` 原样返回分支）
- Modify: `backend/app/graph/nodes/summarize.py`（payload 带 `refine_notes`）
- Modify: `backend/app/graph/state.py`（加 `refine_notes`、`refine_clarification`）
- Test: `backend/tests/test_refine_wiring.py`（新增）

**Interfaces:**
- Consumes：`refine_request["needs_accommodation"]`/`["needs_budget_recheck"]`（Task 3 产出）；`state["refine_clarification"]`（Task 6 产出）；`state["refine_notes"]`（Task 3 产出）
- Produces：`route_after_plan` 在 set_hotel 时返回 `"accommodation"`；`answer` 在有 clarification 时返回 `{"summary": clar, "changed_days": []}`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_refine_wiring.py`：
```python
from app.graph.nodes.routing import route_after_plan, route_after_accommodation
from app.graph.nodes.answer import answer


def test_route_after_plan_hotel_goes_accommodation():
    state = {"last_intent": "refine_existing",
             "refine_request": {"needs_accommodation": True, "needs_budget_recheck": True}}
    assert route_after_plan(state) == "accommodation"


def test_route_after_plan_budget_then_summarize():
    assert route_after_plan({"last_intent": "refine_existing",
                             "refine_request": {"needs_budget_recheck": True}}) == "budget"
    assert route_after_plan({"last_intent": "refine_existing",
                             "refine_request": {"needs_budget_recheck": False}}) == "summarize"


def test_route_after_plan_plan_new_unchanged():
    assert route_after_plan({"last_intent": "plan_new"}) == "accommodation"


async def test_answer_returns_clarification_verbatim_without_llm(monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("澄清分支不应调用 LLM")
    monkeypatch.setattr("app.graph.nodes.answer.build_llm", _boom)
    out = await answer({"refine_clarification": "你想把第几天换到哪里？"}, None)
    assert out["summary"] == "你想把第几天换到哪里？"
    assert out["changed_days"] == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_refine_wiring.py -q`
Expected: FAIL（`route_after_plan` 仍读 `op=="change_hotel"`；`answer` 无澄清分支会调 LLM 触发 `_boom`）

- [ ] **Step 3: 写实现**

`backend/app/graph/nodes/routing.py` 把 `route_after_plan` 改为：
```python
def route_after_plan(state: dict) -> str:
    if (state.get("last_intent") or "plan_new") == "plan_new":
        return "accommodation"
    req = state.get("refine_request", {}) or {}
    if req.get("needs_accommodation"):
        return "accommodation"
    if req.get("needs_budget_recheck"):
        return "budget"
    return "summarize"
```
（`route_after_accommodation` 不变，仍读 `needs_budget_recheck`。）

`backend/app/graph/nodes/answer.py` 在 `async def answer(...)` 函数体最前面加：
```python
    clar = state.get("refine_clarification")
    if clar:
        return {"summary": clar, "changed_days": []}
```

`backend/app/graph/nodes/summarize.py` 把 `day_plans` 分支的 user 文案改为带 notes：
```python
    if day_plans:
        notes = state.get("refine_notes") or {}
        extra = f"\n本轮修改记录（applied/skipped）：{notes}" if notes else ""
        user = f"请根据以下结构化逐日行程，写成中文攻略：\n{day_plans}{extra}\n若有 skipped 项，请如实简述未能完成的部分。"
```

`backend/app/graph/state.py` 在 `TripState` 的「M5 真正多轮上下文」段补两行：
```python
    refine_notes: dict          # refine 本轮 {applied:[...], skipped:[...]}
    refine_clarification: str   # refine 听不懂时向用户反问的话
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_refine_wiring.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/routing.py backend/app/graph/nodes/answer.py backend/app/graph/nodes/summarize.py backend/app/graph/state.py backend/tests/test_refine_wiring.py
git commit -m "feat(m6-v2): 路由按 needs_accommodation 解耦 + 澄清回话 + summarize 诚实回报"
```

---

### Task 8: 迁移剩余 refine 相关测试 + 全量回归

**Files:**
- Modify: `backend/tests/test_refine_budget.py`, `backend/tests/test_refine_transport.py`, `backend/tests/test_multiturn_refine.py`（凡构造 `refine_request={"op":...}` 旧形状处，改为 `{"operations":[{...}]}` 新形状；断言行为不变）
- Test: 全量 `uv run pytest`

**Interfaces:**
- Consumes：Task 3-7 的全部产出
- Produces：无新接口，仅迁移 + 回归

- [ ] **Step 1: 审计旧形状用例**

Run: `cd backend && grep -rn '"op":\|refine_request' tests/test_refine_budget.py tests/test_refine_transport.py tests/test_multiturn_refine.py`
预期：列出所有仍用扁平 `{"op": ...}` 的构造点。对每处按下表等价改写为 operations：

| 旧 | 新 |
|---|---|
| `{"op":"relax","target_day":2}` | `{"operations":[{"op":"set_pace","day":2,"direction":"relax"}]}` |
| `{"op":"reorder","target_day":1}` | `{"operations":[{"op":"reorder","day":1,"strategy":"reverse"}]}` |
| `{"op":"change_budget","constraints":{"budget":3000}}` | `{"operations":[{"op":"set_budget","amount":3000}]}` |
| `{"op":"change_hotel"}` | `{"operations":[{"op":"set_hotel","criteria":"..."}]}` |
| `{"op":"change_meal","constraints":{"keywords":"火锅"}}` | `{"operations":[{"op":"replace_poi","day":N,"kind":"meal","query":"火锅","selector":{"by":"ordinal","kind":"meal","index":0}}]}` |

- [ ] **Step 2: 逐文件改写并单独跑**

对每个文件改写后单独验证：
```bash
cd backend && uv run pytest tests/test_refine_budget.py tests/test_refine_transport.py tests/test_multiturn_refine.py -q
```
Expected: PASS（如某断言依赖旧 center 不变等已变更行为，按新语义更新断言——例如 set_region/检索类改动后 center 会重算）。

- [ ] **Step 3: 全量回归**

Run: `cd backend && uv run pytest -q`
Expected: PASS（全绿；若有非 refine 测试因 `refine_request` 形状假设而挂，按新形状修正）

- [ ] **Step 4: 端到端冒烟（可选但推荐）**

Run: `cd backend && uv run pytest tests/test_multiturn_refine.py tests/test_m5fix_e2e.py -q`
Expected: PASS（确认 dispatch→refine→budget/accommodation→summarize 整链在新形状下连通）

- [ ] **Step 5: 提交**

```bash
git add backend/tests/
git commit -m "test(m6-v2): 迁移 refine 相关测试至 operations 形状 + 全量回归"
```

---

## Self-Review

**Spec coverage（逐节核对）**
- §3 指令集 8 原语：set_region(T5)、add_poi/replace_poi(T4)、remove_poi/reorder/set_pace(T3)、set_budget/set_hotel(T3) ✓；selector 模型(T2) ✓
- §4 解析器：LLM 结构化输出(T6)、day_plans 摘要(T6 `_day_plans_digest`)、标志确定性推导(T3)、空 ops→澄清(T6)、扁平 schema(T1) ✓
- §5 执行器：工作副本+尽力而为+跳过 warning(T3)、统一重建交通+重算 center(T3 `_finalize_day`)、派生标志+notes(T3)、set_region 复用 geometry(T5) ✓
- §6 拓扑/契约：routing 解耦 needs_accommodation(T7)、澄清走 answer(T7)、summarize 带 notes(T7)、state 字段(T7)、7 文件清单全覆盖 ✓
- §7 测试：翻转/删除旧 dispatch 用例(T6)、重写 test_refine_node(T3)、新增复合/set_region/selector/空澄清/诚实 notes(T2-T7)、审计迁移 budget/transport/multiturn(T8) ✓
- §8 风险缓解：selector 命不中跳过(T3)、扁平模型按 op 校验缺失即跳过(T3-T5 各 handler 的 None/缺字段判定) ✓

**Placeholder scan**：无 TBD/TODO；每个代码步均含完整代码与确切命令/预期 ✓

**Type consistency**：`refine_request.operations` 全程为 `list[dict]`；handler 统一签名 `(state, day_plan|dp, op)->tuple[dict,bool,str]`（`_set_region`/`_apply_day_op` 一致）；`_search_insert` 返回 `str|None` 与调用处 `(dp,True,note) if note else (dp,False,...)` 匹配；`_finalize_day` 在 T3 定义、T5 测试引用一致；派生标志键名 `needs_budget_recheck`/`needs_accommodation` 在 T3 产出、T7 路由消费一致 ✓
