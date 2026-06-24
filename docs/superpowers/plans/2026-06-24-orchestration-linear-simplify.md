# 编排线性化简化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前 17 节点 / 6 条件边的 LangGraph 编排收敛为 `START→memory→understand→collect_context→apply→render→memory_update→END` 的 6 节点 0 条件边直线;新规划/改行程/问答三链统一到 operations 模型;新增 preflight 可行性闸门，根治「city 缺失却静默生成雷同行程」一类 bug。

**Architecture:** 算法（OR-Tools 排程）、高德封装、预算/住宿核算逻辑**一行不动**，只重构编排层。先把 weather/attractions/restaurants/transport/retrieve/enrich 的取数逻辑收敛为 `app/planning/context.py` 的纯函数 `collect_context`，把 itinerary 全量排程 + refine 局部改 + accommodation + budget 收敛为 `app/planning/apply.py` 的 `apply_operations`；再用 4 个薄壳单元节点（understand/collect_context/apply/render）调这些纯函数，切图为直线；最后迁移测试、删旧节点、瘦身 state。分阶段：地基（阶段 1-2）纯增量不改图，旧图照常工作；切图（阶段 3）一次性换拓扑；阶段 4-5 清理。

**Tech Stack:** Python 3.13 + LangGraph（StateGraph + interrupt + checkpointer）+ LangChain ChatModel（`build_llm(temperature=0).with_structured_output(Schema, method="function_calling")`）+ pydantic v2 + OR-Tools（已封装于 `app/itinerary/`）+ 高德 amap + pytest（`asyncio_mode=auto`）。前端 Vue 3 + vue-tsc。

## Global Constraints

- 所有 LLM 调用统一走 `app.llm.factory.build_llm(temperature=0).with_structured_output(Schema, method="function_calling")`（与现有节点一致）；测试用 `tests.conftest.make_fake_build_llm(structured=...)` / `make_fake_build_llm(tokens=...)` 打桩，绝不依赖真实 LLM/高德网络（高德用 `fake_amap` fixture）。
- 依赖优先原则（项目 CLAUDE.md）：**不重写算法**。复用 `app/itinerary/`（`prefilter.select_candidates`/`matrix.distance_matrix`/`optimizer.solve_vrptw`/`assembler.routes_to_skeleton`/`opentime.parse_opentime`/`geometry.*`/`soft_fill.annotate_soft_fields`）、`app/graph/nodes/budget.compute_budget`、`app/graph/nodes/accommodation`（住宿分配）、`app/graph/nodes/refine` 的纯 helper（`_apply_day_op`/`_finalize_day`/`_overnight_days`/`_find_day`/`_relax_stops` 等）、`app/graph/nodes/time_budget`（`DAY_BUDGET`/`LUNCH_MIN`/`DINNER_MIN`/`day_used_minutes`）。
- **能力函数从原始模块 import，不经 `app.graph.nodes.itinerary` re-export**：apply/context 一律 `from app.itinerary.xxx import ...`、`from app.tools import amap`，使阶段 5 删除旧节点壳时这些 import 不受影响。
- 高德 Key 绝不进日志/SSE/前端（沿用现状）。
- 代码与用户可见文案用简体中文；注释风格与既有节点一致。
- 测试一律 `cd backend && uv run pytest`（系统 python 缺 pytest-asyncio）。
- **派生标志确定性**（沿用 refine 现状）：`needs_budget_recheck = 任一 op != "reorder"`；`needs_accommodation = 任一 op == "set_hotel"`；`replace_plan` 同时置两者为真；`plan_version` 仅当有结构变化（`changed` 非空）才 +1。
- **city bug 根因**：顶层 `city` 只在 plan_new 写、refine 不写；但 `normalized_req["city"]` 在 plan_new 已写入。preflight 的 city 补救一律从 `normalized_req`/`state` 确定性读取，不引入逆地理网络调用。
- **不破坏既有契约**：保留 `app/graph/nodes/itinerary.py` 的全部 re-export（`haversine_km`/`insert_transport`/`build_day_stops`/`DayPlans`/`PlanItem`/`Hotel`/`Location` 等），11+ 测试依赖旧路径；阶段 5 仅删节点函数本体，保留 re-export/纯 helper 模块。

---

## 阶段 1：operations 模型扩展 + preflight（纯增量，不改图）

### Task 1: Operation 模型扩展（replace_plan / answer_only + requirements_patch + question）

**Files:**
- Modify: `backend/app/graph/nodes/refine_ops.py`
- Test: `backend/tests/test_refine_ops_schema.py`（扩展，保留现有用例不破坏）

**Interfaces:**
- Consumes：无（schema 基础任务）
- Produces：
  - `Operation.op` 字面量在原 8 个基础上新增 `"replace_plan"`、`"answer_only"`
  - `Operation.requirements_patch: dict = {}`（replace_plan 承载 city/days/budget 等需求补丁）
  - `Operation.question: str = ""`（answer_only 承载用户问题）
  - `RefinePlan` 不变

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_refine_ops_schema.py` **末尾追加**（保留原有 5 个用例）：
```python
def test_operation_replace_plan_carries_requirements_patch():
    op = Operation(op="replace_plan", requirements_patch={"city": "广州", "days": 3})
    assert op.op == "replace_plan"
    assert op.requirements_patch == {"city": "广州", "days": 3}
    assert op.question == ""


def test_operation_answer_only_carries_question():
    op = Operation(op="answer_only", question="为什么第二天这么赶？")
    assert op.op == "answer_only" and op.question == "为什么第二天这么赶？"
    assert op.requirements_patch == {}


def test_operation_defaults_for_new_fields():
    op = Operation(op="reorder", day=1)
    assert op.requirements_patch == {} and op.question == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_refine_ops_schema.py -q`
Expected: FAIL（`ValidationError: Input should be 'set_region'...` —— "replace_plan" 不在 Literal）

- [ ] **Step 3: 写实现**

在 `backend/app/graph/nodes/refine_ops.py` 的 `Operation` 类：把 `op` 字面量与新增两字段改为：
```python
class Operation(BaseModel):
    op: Literal[
        "replace_plan",      # 全量（重）规划，需求经 requirements_patch 承载
        "set_region", "add_poi", "remove_poi", "replace_poi",
        "reorder", "set_pace", "set_budget", "set_hotel",
        "answer_only",       # 不改计划，纯问答
    ] = Field(description="原子操作类型；决定本条其余字段的语义")
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
    requirements_patch: dict = Field(default_factory=dict, description="replace_plan：city/days/budget/preferences 等需求补丁")
    question: str = Field(default="", description="answer_only：用户的问题原文")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_refine_ops_schema.py -q`
Expected: PASS（8 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/refine_ops.py backend/tests/test_refine_ops_schema.py
git commit -m "feat(linear): Operation 扩展 replace_plan/answer_only + requirements_patch/question

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: preflight 可行性闸门（依赖表 + 确定性校验 + city 补救 + 裁决）

**Files:**
- Create: `backend/app/planning/__init__.py`（空文件）
- Create: `backend/app/planning/preflight.py`
- Test: `backend/tests/test_preflight.py`

**Interfaces:**
- Consumes：Task 1 的 `Operation`（以 dict 形态流转）；`state` 字典（含 `day_plans`/`normalized_req`/`city`/`conversation_summary`）
- Produces：
  - `OP_REQUIREMENTS: dict[str, list[str]]` —— op → 依赖键列表
  - `def infer_city(state: dict) -> str` —— 确定性反推城市（normalized_req → state → 会话摘要正则），无则 `""`
  - `class PreflightResult(BaseModel)`：`operations: list[dict]`（含补救后的 patch）、`blocked: list[dict]`（`[{index,op,missing,reason}]`）、`clarification: str`（可由用户补的反问；无则 `""`）
  - `def preflight(operations: list[dict], state: dict) -> PreflightResult`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_preflight.py`：
```python
from app.planning.preflight import preflight, infer_city, OP_REQUIREMENTS, PreflightResult


def _plan():
    return [{"day": 1, "items": [{"type": "attraction", "name": "越秀公园"}]},
            {"day": 2, "items": [{"type": "attraction", "name": "陈家祠"}]}]


def test_op_requirements_covers_all_ops():
    for op in ("replace_plan", "set_region", "add_poi", "remove_poi", "replace_poi",
               "reorder", "set_pace", "set_budget", "set_hotel", "answer_only"):
        assert op in OP_REQUIREMENTS


def test_infer_city_from_normalized_req():
    assert infer_city({"normalized_req": {"city": "广州"}}) == "广州"


def test_infer_city_falls_back_to_top_level():
    assert infer_city({"city": "成都"}) == "成都"


def test_infer_city_empty_when_unknown():
    assert infer_city({"day_plans": _plan()}) == ""


def test_set_region_patches_city_from_normalized_req():
    ops = [{"op": "set_region", "day": 1, "area": "黄埔"}]
    res = preflight(ops, {"normalized_req": {"city": "广州"}, "day_plans": _plan()})
    assert isinstance(res, PreflightResult)
    assert res.operations[0]["requirements_patch"]["city"] == "广州"
    assert res.blocked == [] and res.clarification == ""


def test_set_region_missing_city_asks_clarification():
    ops = [{"op": "set_region", "day": 1, "area": "黄埔"}]
    res = preflight(ops, {"day_plans": _plan()})   # 无 city 任何来源
    assert res.clarification          # 反问城市
    assert any(b["op"] == "set_region" and "city" in b["missing"] for b in res.blocked)


def test_set_region_missing_day_is_blocked_for_render():
    ops = [{"op": "set_region", "day": 9, "area": "黄埔"}]
    res = preflight(ops, {"normalized_req": {"city": "广州"}, "day_plans": _plan()})
    assert any(b["op"] == "set_region" and "day_exists" in b["missing"] for b in res.blocked)


def test_replace_plan_needs_city_and_days():
    ok = preflight([{"op": "replace_plan", "requirements_patch": {"city": "广州", "days": 3}}], {})
    assert ok.blocked == [] and ok.clarification == ""
    bad = preflight([{"op": "replace_plan", "requirements_patch": {"days": 3}}], {})
    assert bad.clarification and any("city" in b["missing"] for b in bad.blocked)


def test_set_budget_missing_amount_blocked():
    res = preflight([{"op": "set_budget"}], {"day_plans": _plan()})
    assert any(b["op"] == "set_budget" and "amount" in b["missing"] for b in res.blocked)


def test_answer_only_always_ok():
    res = preflight([{"op": "answer_only", "question": "为什么这么赶"}], {})
    assert res.blocked == [] and res.clarification == ""


def test_local_op_ok_when_day_exists():
    res = preflight([{"op": "reorder", "day": 1}], {"day_plans": _plan()})
    assert res.blocked == [] and res.clarification == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_preflight.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.planning'`）

- [ ] **Step 3: 写实现**

创建空文件 `backend/app/planning/__init__.py`（无内容）。

创建 `backend/app/planning/preflight.py`：
```python
"""preflight 可行性闸门：op 声明依赖 → 确定性校验 → 补救 → 裁决。

裁决三态（设计 §6）：
- 全部满足 → operations 原样（含补救后的 requirements_patch）放行。
- 缺信息但**可由用户补**（如 city）→ 进 blocked + 给 clarification，understand 节点据此 interrupt 反问。
- 缺信息且**不可由用户即时补**（如 day 不存在 / 缺 amount）→ 进 blocked、不给 clarification，交 render 诚实回报。

判定全部是确定性代码；LLM 不参与（understand 节点只负责把 clarification 转成自然语言反问，本模块已给出可直接用的中文反问句）。
"""
import re

from pydantic import BaseModel, Field

# op → 依赖键列表。键语义见 _check 内部判定。
OP_REQUIREMENTS: dict[str, list[str]] = {
    "replace_plan": ["city", "days"],
    "set_region": ["city", "area", "day_exists"],
    "add_poi": ["day_exists"],
    "replace_poi": ["day_exists"],
    "remove_poi": ["day_exists"],
    "reorder": ["day_exists"],
    "set_pace": ["day_exists"],
    "set_budget": ["amount"],
    "set_hotel": ["overnight_exists"],
    "answer_only": [],
}

# 缺失这些键时可走 interrupt 反问用户补；其余缺失只能 render 回报。
_USER_FILLABLE = {"city", "days"}

_CITY_RE = re.compile(r"([一-龥]{2,4})(?:市|区)?")


class PreflightResult(BaseModel):
    operations: list[dict] = Field(default_factory=list)
    blocked: list[dict] = Field(default_factory=list)     # [{index, op, missing:[...], reason}]
    clarification: str = ""                                # 需 interrupt 反问的中文句；无则空


def infer_city(state: dict) -> str:
    """确定性反推城市：normalized_req.city → 顶层 city → 会话摘要里的城市名。推不出返回 ""。"""
    req = state.get("normalized_req", {}) or {}
    city = (req.get("city") or state.get("city") or "").strip()
    if city:
        return city
    summary = state.get("conversation_summary", "") or ""
    m = _CITY_RE.search(summary)
    return m.group(1) if m else ""


def _day_exists(state: dict, day) -> bool:
    return any(d.get("day") == day for d in (state.get("day_plans") or []))


def _overnight_exists(state: dict) -> bool:
    return len(state.get("day_plans") or []) > 1


def _check(op: dict, state: dict) -> tuple[list[str], dict]:
    """返回 (缺失键列表, 该 op 的 requirements_patch 补救增量)。"""
    kind = op.get("op")
    missing: list[str] = []
    patch = dict(op.get("requirements_patch") or {})
    for need in OP_REQUIREMENTS.get(kind, []):
        if need == "city":
            city = (patch.get("city") or "").strip() or infer_city(state)
            if city:
                patch["city"] = city
            else:
                missing.append("city")
        elif need == "days":
            days = patch.get("days") or (state.get("normalized_req", {}) or {}).get("days")
            if days:
                patch["days"] = days
            else:
                missing.append("days")
        elif need == "area":
            if not (op.get("area") or "").strip():
                missing.append("area")
        elif need == "day_exists":
            if not _day_exists(state, op.get("day")):
                missing.append("day_exists")
        elif need == "amount":
            if op.get("amount") is None:
                missing.append("amount")
        elif need == "overnight_exists":
            if not _overnight_exists(state):
                missing.append("overnight_exists")
    return missing, patch


def _clarify_sentence(op: dict, missing: list[str]) -> str:
    if "city" in missing:
        area = (op.get("area") or "").strip()
        tail = f"把第{op.get('day')}天改到「{area}」" if area else "重新规划"
        return f"我不确定当前是哪个城市，没法{tail}，方便告诉我城市吗？"
    if "days" in missing:
        return "你想安排几天的行程呢？"
    return ""


def preflight(operations: list[dict], state: dict) -> PreflightResult:
    out_ops: list[dict] = []
    blocked: list[dict] = []
    clarification = ""
    for i, op in enumerate(operations):
        missing, patch = _check(op, state)
        new_op = {**op, "requirements_patch": patch}
        out_ops.append(new_op)
        if missing:
            blocked.append({"index": i, "op": op.get("op"), "missing": missing,
                            "reason": "缺少必要信息：" + "、".join(missing)})
            if not clarification and any(m in _USER_FILLABLE for m in missing):
                clarification = _clarify_sentence(op, missing)
    return PreflightResult(operations=out_ops, blocked=blocked, clarification=clarification)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_preflight.py -q`
Expected: PASS（11 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/planning/__init__.py backend/app/planning/preflight.py backend/tests/test_preflight.py
git commit -m "feat(linear): preflight 可行性闸门（依赖表+city确定性补救+裁决）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## 阶段 2：能力函数化（纯模块，不改图）

### Task 3: collect_context 按需取数纯函数

**Files:**
- Create: `backend/app/planning/context.py`
- Test: `backend/tests/test_context.py`

**Interfaces:**
- Consumes：`app.tools.amap`（`get_weather`/`search_poi`，`fake_amap` 可控）；`Operation` dict（含补救后的 `requirements_patch`）
- Produces：`async def collect_context(operations: list[dict], state: dict, config=None) -> dict`
  - 返回 `{"weather": dict, "attractions": list, "restaurants": list}`
  - 仅当存在 `replace_plan` op 时取全量（天气 + 全城景点池 + 全城餐饮池，`asyncio.gather` 并发）；否则返回三者空（局部 op 的检索由 apply 复用的 refine handler 现场完成，见 Task 5 说明）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_context.py`：
```python
from app.planning.context import collect_context


async def test_collect_context_replace_plan_fetches_all(fake_amap):
    fake_amap["get_weather"] = {"text": "晴", "temp": "20~28℃", "is_rainy": False, "source": "forecast"}
    fake_amap["search_poi"] = [{"name": "越秀公园", "poi_id": "G1", "lng": 113.27, "lat": 23.13}]
    ops = [{"op": "replace_plan", "requirements_patch": {"city": "广州", "days": 3}}]
    ctx = await collect_context(ops, {"normalized_req": {"city": "广州"}})
    assert ctx["weather"]["text"] == "晴"
    assert ctx["attractions"] and ctx["attractions"][0]["name"] == "越秀公园"
    assert ctx["restaurants"] is not None


async def test_collect_context_local_op_fetches_nothing(fake_amap):
    fake_amap["search_poi"] = [{"name": "不该被取", "poi_id": "X"}]
    ctx = await collect_context([{"op": "reorder", "day": 1}], {})
    assert ctx["attractions"] == [] and ctx["restaurants"] == [] and ctx["weather"] == {}


async def test_collect_context_uses_preferences_keywords(fake_amap):
    captured = {}

    async def _spy(city, keywords, poi_type="", page_size=20):
        captured.setdefault(poi_type, keywords)
        return []
    import app.tools.amap as amap
    amap.search_poi = _spy   # fake_amap 已 patch，这里再覆盖以捕获关键词
    ops = [{"op": "replace_plan", "requirements_patch": {"city": "广州", "days": 2}}]
    await collect_context(ops, {"normalized_req": {"preferences": {"travel": "博物馆", "food": "粤菜"}}})
    assert captured.get("风景名胜") == "博物馆"
    assert captured.get("餐饮") == "粤菜"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_context.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.planning.context'`）

- [ ] **Step 3: 写实现**

创建 `backend/app/planning/context.py`：
```python
"""collect_context：按 operations 类型确定性地预取数据（纯能力函数，不进图）。

设计 §8 的精简落地：仅 replace_plan 需要全量池（喂 OR-Tools）；局部 op 的检索
（add_poi/replace_poi/set_region）由 apply 复用的 refine handler 现场完成，故此处
对局部 op 不取数（返回空），避免重复检索与重写已测逻辑。
"""
import asyncio

from app.tools import amap


def _req(state: dict) -> dict:
    return state.get("normalized_req", {}) or {}


async def collect_context(operations: list[dict], state: dict, config=None) -> dict:
    """按需取数。当前仅 replace_plan 触发全量并发检索。"""
    empty = {"weather": {}, "attractions": [], "restaurants": []}
    replace = next((o for o in operations if o.get("op") == "replace_plan"), None)
    if replace is None:
        return empty

    req = {**_req(state), **(replace.get("requirements_patch") or {})}
    city = (req.get("city") or "").strip()
    prefs = req.get("preferences", {}) or {}
    attr_kw = prefs.get("travel") or prefs.get("theme") or "热门景点"
    food_kw = prefs.get("food") or "美食"
    if not city:
        return empty

    async def _weather():
        try:
            return await amap.get_weather(city)
        except Exception:  # noqa: BLE001
            return {}

    async def _attractions():
        try:
            return await amap.search_poi(city, attr_kw, "风景名胜")
        except Exception:  # noqa: BLE001
            return []

    async def _restaurants():
        try:
            return await amap.search_poi(city, food_kw, "餐饮")
        except Exception:  # noqa: BLE001
            return []

    w, a, r = await asyncio.gather(_weather(), _attractions(), _restaurants())
    return {"weather": w, "attractions": a, "restaurants": r}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_context.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/planning/context.py backend/tests/test_context.py
git commit -m "feat(linear): collect_context 按需取数纯函数（replace_plan 触发全量并发）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: apply.py —— replace_plan 全量排程分支（搬迁 itinerary 编排，不改算法）

**Files:**
- Create: `backend/app/planning/apply.py`
- Test: `backend/tests/test_apply_replace_plan.py`

**Interfaces:**
- Consumes：`app.itinerary.prefilter.select_candidates`、`app.itinerary.matrix.distance_matrix`、`app.itinerary.optimizer.solve_vrptw`、`app.itinerary.assembler.routes_to_skeleton`、`app.itinerary.opentime.parse_opentime`、`app.itinerary.soft_fill.annotate_soft_fields`、`app.graph.nodes.time_budget`（`DAY_BUDGET`/`LUNCH_MIN`/`DINNER_MIN`）、`app.core.constants.AROUND_RADIUS_M`、`app.core.config.get_settings`、`app.tools.amap`；Task 3 的 `collect_context` 产出
- Produces：`async def replace_plan(req: dict, context: dict, state: dict, config=None) -> dict`
  - 返回 `{"daily_centers": list, "day_plans": list, "dropped_attractions": list, "relax_level": int}`（与 `itinerary()` 现有产出同形，但去掉 plan_version/changed_days，由 apply 顶层统一算）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_apply_replace_plan.py`：
```python
from app.planning.apply import replace_plan


async def test_replace_plan_empty_attractions_returns_empty(fake_amap):
    out = await replace_plan({"city": "广州", "days": 2}, {"attractions": [], "restaurants": []}, {})
    assert out["day_plans"] == [] and out["daily_centers"] == []
    assert out["relax_level"] == 0


async def test_replace_plan_builds_day_plans_from_pool(fake_amap, monkeypatch):
    # 提供 6 个分散景点 + 餐饮池，走真实 OR-Tools 纯函数链（距离用 haversine 降级）
    attrs = [{"name": f"景点{i}", "poi_id": f"A{i}", "lng": 113.2 + i * 0.02, "lat": 23.1 + i * 0.01,
              "rating": 4.5, "opentime": ""} for i in range(6)]
    rests = [{"name": f"餐厅{i}", "poi_id": f"R{i}", "lng": 113.2 + i * 0.02, "lat": 23.1, "type": "餐饮"}
             for i in range(4)]
    fake_amap["search_around"] = rests
    ctx = {"weather": {}, "attractions": attrs, "restaurants": rests}
    out = await replace_plan({"city": "广州", "days": 2, "preferences": {}}, ctx,
                             {"plan_version": 0}, None)
    assert len(out["day_plans"]) >= 1
    # 每天 items 含交通段交错（M6 不变量），首项非交通
    items = out["day_plans"][0]["items"]
    assert items and items[0].get("type") != "transport"
    assert all("center" in d for d in out["day_plans"])
```

> 说明：`replace_plan` 内部对每天簇中心调 `amap.search_around` 取餐厅池，已被 `fake_amap` 桩成 `rests`；`annotate_soft_fields` 调 LLM 软填——测试需打桩 `app.itinerary.soft_fill.build_llm`。在 Step 1 文件顶部追加 fixture 自动打桩：
```python
import pytest
from langchain_core.messages import AIMessage


@pytest.fixture(autouse=True)
def _stub_soft_fill(monkeypatch):
    """annotate_soft_fields 调 LLM 软填；桩成回显 skeleton（不改结构）。"""
    from app.itinerary import soft_fill

    class _Echo:
        def with_structured_output(self, *a, **k):
            return self

        async def ainvoke(self, *a, **k):
            # 软填 LLM 失败时 annotate_soft_fields 已有降级；这里直接抛让其走降级返回 skeleton
            raise RuntimeError("stub: skip soft fill")

    monkeypatch.setattr(soft_fill, "build_llm", lambda *a, **k: _Echo())
```
（若 `annotate_soft_fields` 无异常降级分支，则改桩为返回合法 `_Durations`/软字段结构——实现 Step 3 前先 `uv run pytest tests/test_itinerary.py -q` 看现有软填测试如何打桩并对齐。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_apply_replace_plan.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.planning.apply'`）

- [ ] **Step 3: 写实现**

创建 `backend/app/planning/apply.py`（本任务只放 `replace_plan`，Task 5/6 续接同文件）：
```python
"""apply：operations 确定性执行器（纯能力函数，不进图）。

- replace_plan：复用 app.itinerary 全量排程链（OR-Tools），不改算法。
- 局部 op（Task 5）：复用 app.graph.nodes.refine 的 _apply_day_op 系列。
- 住宿/预算重算（Task 6）：复用 accommodation / budget.compute_budget。
能力函数一律从原始模块 import，不经 nodes.itinerary re-export。
"""
from app.core.config import get_settings
from app.core.constants import AROUND_RADIUS_M
from app.graph.nodes.time_budget import DAY_BUDGET, LUNCH_MIN, DINNER_MIN
from app.itinerary.prefilter import select_candidates
from app.itinerary.matrix import distance_matrix
from app.itinerary.optimizer import solve_vrptw
from app.itinerary.assembler import routes_to_skeleton
from app.itinerary.opentime import parse_opentime
from app.itinerary.soft_fill import annotate_soft_fields
from app.tools import amap
import os


def _distance_cache_path(checkpoint_db_path: str) -> str:
    d = os.path.dirname(checkpoint_db_path) or "."
    return os.path.join(d, "distance_cache.sqlite")


async def replace_plan(req: dict, context: dict, state: dict, config=None) -> dict:
    """全量重排：消费 context 的景点/餐饮池，跑 OR-Tools，装配 + LLM 软填。
    返回 {daily_centers, day_plans, dropped_attractions, relax_level}。逻辑与原
    itinerary() 一致，仅把入参从 state 改为 (req, context)。"""
    days = req.get("days", 3) or 3
    attractions = context.get("attractions", []) or []
    candidates, dropped_pre = select_candidates(attractions, days)
    if not candidates:
        return {"daily_centers": [], "day_plans": [], "dropped_attractions": dropped_pre, "relax_level": 0}

    cx = sum(p["lng"] for p in candidates) / len(candidates)
    cy = sum(p["lat"] for p in candidates) / len(candidates)
    depot = {"name": "__depot__", "poi_id": "__depot__", "lng": cx, "lat": cy, "visit_minutes": 0}
    nodes = [depot] + candidates

    db_path = _distance_cache_path(get_settings().checkpoint_db_path)
    matrix = await distance_matrix(nodes, db_path)

    ratings = [0.0] + [p.get("rating", 3.0) for p in candidates]
    tw = [(0, DAY_BUDGET)] + [parse_opentime(p.get("opentime", ""), DAY_BUDGET) for p in candidates]
    solve_budget = max(1, DAY_BUDGET - (LUNCH_MIN + DINNER_MIN))
    routes, dropped_idx, relax = solve_vrptw(matrix, nodes, days, solve_budget,
                                             time_windows=tw, ratings=ratings)

    food_kw = (req.get("preferences") or {}).get("food") or "美食"
    city_pool = context.get("restaurants", []) or []
    rest_pools = []
    for route in routes:
        pts = [candidates[i - 1] for i in route if 1 <= i <= len(candidates)]
        if pts:
            cx2 = sum(p["lng"] for p in pts) / len(pts)
            cy2 = sum(p["lat"] for p in pts) / len(pts)
            pool = await amap.search_around(cx2, cy2, food_kw, "餐饮", AROUND_RADIUS_M) or city_pool
        else:
            pool = city_pool
        rest_pools.append(pool)

    skeleton, centers = routes_to_skeleton(routes, candidates, rest_pools)
    # 软填需要 state 提供 weather 等；把 context.weather 注入 state 副本供 build_soft_payload 使用
    soft_state = {**state, "weather": context.get("weather", {}) or {},
                  "days": days, "preferences": req.get("preferences", {}) or {}}
    day_plans = await annotate_soft_fields(skeleton, soft_state, config)

    dropped_solver = [{"name": candidates[i - 1].get("name", ""),
                       "rating": candidates[i - 1].get("rating", 0.0),
                       "reason": "综合距离/时间/评分权衡后未排入"}
                      for i in dropped_idx if 1 <= i <= len(candidates)]
    return {"daily_centers": centers, "day_plans": day_plans,
            "dropped_attractions": dropped_pre + dropped_solver, "relax_level": relax}
```

> 实现注意：`annotate_soft_fields(skeleton, soft_state, config)` 的第二参数在原 `itinerary()` 里是 `state`。Step 3 写前先 `rg "def annotate_soft_fields|def build_soft_payload" backend/app/itinerary/soft_fill.py` 确认它读 state 的哪些键（weather/days/preferences/city），把这些键都并入 `soft_state`，保证软填 payload 不退化。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_apply_replace_plan.py -q`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/planning/apply.py backend/tests/test_apply_replace_plan.py
git commit -m "feat(linear): apply.replace_plan 搬迁 itinerary 全量排程编排（不改算法）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: apply.py —— 局部 op + 顶层 apply_operations 主循环（复用 refine handler）

**Files:**
- Modify: `backend/app/planning/apply.py`（新增 `apply_operations` 主循环）
- Test: `backend/tests/test_apply_operations.py`

**Interfaces:**
- Consumes：Task 4 的 `replace_plan`；`app.graph.nodes.refine` 的纯 helper `_apply_day_op`/`_finalize_day`/`_find_day`/`_overnight_days`（从 refine 模块 import，阶段 5 保留为 helper）
- Produces：`async def apply_operations(operations: list[dict], context: dict, state: dict, config=None) -> dict`
  - 返回 `{day_plans, changed_days, plan_version, daily_centers, dropped_attractions, relax_level, applied, skipped, needs_accommodation, needs_budget_recheck, budget?}`
  - 本任务**先不接住宿/预算重算**（仅置 needs 标志），Task 6 接上 `budget_check`/住宿嵌入

- [ ] **Step 1: 写失败测试**

`backend/tests/test_apply_operations.py`：
```python
from app.planning.apply import apply_operations
from app.graph.nodes.itinerary import insert_transport


def _plan():
    day1 = [{"type": "attraction", "name": "武侯祠", "poi_id": "B1", "location": {"lng": 104.05, "lat": 30.65}},
            {"type": "meal", "name": "陈麻婆", "poi_id": "M1", "location": {"lng": 104.06, "lat": 30.66}}]
    day2 = [{"type": "attraction", "name": "杜甫草堂", "poi_id": "B2", "location": {"lng": 104.04, "lat": 30.67}},
            {"type": "attraction", "name": "金沙遗址", "poi_id": "B3", "location": {"lng": 104.03, "lat": 30.68}}]
    return [{"day": 1, "items": insert_transport(day1), "center": {"lng": 104.055, "lat": 30.655}},
            {"day": 2, "items": insert_transport(day2), "center": {"lng": 104.035, "lat": 30.675}}]


async def test_apply_reorder_only_target_day():
    state = {"day_plans": _plan(), "plan_version": 1}
    out = await apply_operations([{"op": "reorder", "day": 1, "strategy": "reverse"}], {}, state)
    assert out["changed_days"] == [1]
    stops = [i["name"] for i in out["day_plans"][0]["items"] if i.get("type") != "transport"]
    assert stops == ["陈麻婆", "武侯祠"]
    assert out["needs_budget_recheck"] is False
    assert out["day_plans"][1]["items"] == _plan()[1]["items"]


async def test_apply_remove_poi_miss_is_honest_skip():
    state = {"day_plans": _plan(), "plan_version": 1}
    out = await apply_operations(
        [{"op": "remove_poi", "day": 1, "selector": {"by": "name", "name": "不存在"}}], {}, state)
    assert out["changed_days"] == [] and out["plan_version"] == 1
    assert out["skipped"] and not out["applied"]


async def test_apply_set_budget_sets_flag_and_value():
    state = {"day_plans": _plan(), "plan_version": 1, "budget": 5000}
    out = await apply_operations([{"op": "set_budget", "amount": 3000.0}], {}, state)
    assert out["budget"] == 3000.0 and out["needs_budget_recheck"] is True
    assert out["changed_days"] == []


async def test_apply_set_hotel_flags_accommodation():
    state = {"day_plans": _plan(), "plan_version": 1}
    out = await apply_operations([{"op": "set_hotel", "criteria": "离地铁近"}], {}, state)
    assert out["needs_accommodation"] is True and out["changed_days"] == [1]
    assert out["plan_version"] == 2


async def test_apply_replace_plan_sets_both_flags(fake_amap, monkeypatch):
    from app.planning import apply as apply_mod

    async def _fake_replace(req, context, state, config=None):
        return {"daily_centers": [{"lng": 113.2, "lat": 23.1}],
                "day_plans": [{"day": 1, "items": [], "center": {"lng": 113.2, "lat": 23.1}}],
                "dropped_attractions": [], "relax_level": 0}
    monkeypatch.setattr(apply_mod, "replace_plan", _fake_replace)
    out = await apply_operations(
        [{"op": "replace_plan", "requirements_patch": {"city": "广州", "days": 1}}],
        {"attractions": [], "restaurants": []}, {"plan_version": 2})
    assert out["needs_accommodation"] is True and out["needs_budget_recheck"] is True
    assert out["changed_days"] == [1] and out["plan_version"] == 3


async def test_apply_answer_only_is_noop_on_plan():
    state = {"day_plans": _plan(), "plan_version": 1}
    out = await apply_operations([{"op": "answer_only", "question": "为什么"}], {}, state)
    assert out["day_plans"] == _plan() and out["changed_days"] == []
    assert out["plan_version"] == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_apply_operations.py -q`
Expected: FAIL（`ImportError: cannot import name 'apply_operations'`）

- [ ] **Step 3: 写实现**

在 `backend/app/planning/apply.py` 顶部 import 区追加：
```python
from copy import deepcopy

from app.graph.nodes.refine import _apply_day_op, _finalize_day, _find_day, _overnight_days
```
在文件末尾新增 `apply_operations`：
```python
async def apply_operations(operations: list[dict], context: dict, state: dict, config=None) -> dict:
    """按序执行 operations，统一收尾 + 诚实回报。住宿/预算重算在 Task 6 接入。"""
    day_plans = deepcopy(state.get("day_plans", []) or [])
    centers = list(state.get("daily_centers", []) or [])
    dropped = list(state.get("dropped_attractions", []) or [])
    relax = state.get("relax_level", 0)
    applied: list[str] = []
    skipped: list[str] = []
    changed: set[int] = set()
    touched: set[int] = set()
    needs_accom = False
    budget_new = None

    for op in operations:
        kind = op.get("op")
        if kind == "answer_only":
            continue
        if kind == "replace_plan":
            req = {**(state.get("normalized_req") or {}), **(op.get("requirements_patch") or {})}
            res = await replace_plan(req, context, state, config)
            day_plans = res["day_plans"]
            centers = res["daily_centers"]
            dropped = res["dropped_attractions"]
            relax = res["relax_level"]
            changed = {d.get("day") for d in day_plans}
            touched = set()   # replace_plan 产出已 finalize（含交通段+center）
            needs_accom = True
            applied.append(f"已重新规划 {len(day_plans)} 天行程")
            continue
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
        # 局部按天 op：复用 refine handler
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

    for d in touched:
        i = _find_day(day_plans, d)
        if i is not None:
            day_plans[i] = _finalize_day(day_plans[i])

    needs_budget = any(o.get("op") != "reorder" and o.get("op") != "answer_only" for o in operations)
    plan_version = (state.get("plan_version", 0) or 0) + (1 if changed else 0)
    out: dict = {
        "day_plans": day_plans,
        "daily_centers": centers,
        "dropped_attractions": dropped,
        "relax_level": relax,
        "changed_days": sorted(c for c in changed if c is not None),
        "plan_version": plan_version,
        "applied": applied,
        "skipped": skipped,
        "needs_accommodation": needs_accom,
        "needs_budget_recheck": needs_budget,
    }
    if budget_new is not None:
        out["budget"] = budget_new
    return out
```

> 注：`needs_budget_recheck` 沿用 refine 口径「任一 op != reorder」，并把 `answer_only` 一并排除（纯问答不触发预算）。`replace_plan` 不是 reorder → 自然为真。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_apply_operations.py -q`
Expected: PASS（6 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/planning/apply.py backend/tests/test_apply_operations.py
git commit -m "feat(linear): apply_operations 主循环（replace_plan/局部op/budget/hotel + 诚实回报）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: apply.py —— 住宿重算 + 预算重算接入

**Files:**
- Modify: `backend/app/graph/nodes/accommodation.py`（抽 `async def assign_hotels(day_plans, city, preferences, daily_centers, config) -> list`，`accommodation()` 节点改为薄壳调它——保持现有节点行为不变）
- Modify: `backend/app/planning/apply.py`（`apply_operations` 末尾接住宿 + 预算重算）
- Test: `backend/tests/test_apply_recompute.py`

**Interfaces:**
- Consumes：`app.graph.nodes.accommodation.assign_hotels`、`app.graph.nodes.budget.compute_budget`
- Produces：
  - `async def assign_hotels(day_plans, city, preferences, daily_centers, config=None) -> list`（返回嵌入 hotel 后的 day_plans）
  - `apply_operations` 输出新增 `budget_check`（当 `needs_budget_recheck` 且有 limit 时）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_apply_recompute.py`：
```python
from app.planning.apply import apply_operations
from app.graph.nodes.itinerary import insert_transport
from tests.conftest import make_fake_build_llm


def _plan():
    day1 = [{"type": "attraction", "name": "A", "poi_id": "B1", "location": {"lng": 104.05, "lat": 30.65},
             "cost": 60.0}]
    day2 = [{"type": "attraction", "name": "B", "poi_id": "B2", "location": {"lng": 104.04, "lat": 30.67},
             "cost": 60.0}]
    return [{"day": 1, "items": insert_transport(day1), "center": {"lng": 104.05, "lat": 30.65}},
            {"day": 2, "items": insert_transport(day2), "center": {"lng": 104.04, "lat": 30.67}}]


async def test_apply_set_budget_recomputes_budget_check():
    state = {"day_plans": _plan(), "plan_version": 1, "num_people": 1, "budget": 5000}
    out = await apply_operations([{"op": "set_budget", "amount": 3000.0}], {}, state)
    assert out["budget"] == 3000.0
    assert out["budget_check"]["limit"] == 3000.0
    assert "estimated" in out["budget_check"]


async def test_apply_set_hotel_reassigns_hotels(monkeypatch, fake_amap):
    from app.graph.nodes import accommodation as acc
    monkeypatch.setattr(acc, "build_llm", make_fake_build_llm(
        structured=acc._AccoResult(assignments=[
            acc._HotelForDay(day=1, hotel=acc.Hotel(name="测试酒店", poi_id="H1",
                                                    location=acc.Location(lng=104.05, lat=30.65), price=400.0))])))
    state = {"day_plans": _plan(), "plan_version": 1, "city": "成都", "num_people": 1,
             "budget": 5000, "daily_centers": [{"lng": 104.05, "lat": 30.65}]}
    out = await apply_operations([{"op": "set_hotel", "criteria": "离地铁近"}], {}, state)
    assert out["day_plans"][0].get("hotel", {}).get("name") == "测试酒店"   # 过夜日(第1天)嵌入酒店
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_apply_recompute.py -q`
Expected: FAIL（`apply_operations` 输出无 `budget_check`；住宿未重排）

- [ ] **Step 3: 写实现**

**(a)** 在 `backend/app/graph/nodes/accommodation.py` 抽出能力函数（把 `accommodation()` 体改写为调 `assign_hotels`）：
```python
async def assign_hotels(day_plans: list, city: str, preferences: dict,
                        daily_centers: list, config=None) -> list:
    """检索酒店 + LLM 按档位/就近分配，嵌回 day_plans。无过夜日返回原 day_plans。纯能力函数。"""
    nights = overnight_days(day_plans)
    if not nights:
        return day_plans
    prefs = preferences or {}
    level = prefs.get("住宿") or prefs.get("accommodation") or "舒适"
    try:
        pool = await amap.search_poi(city, hotel_keyword(level), "住宿服务") if city else []
    except Exception:  # noqa: BLE001
        pool = []
    llm = build_llm(temperature=0).with_structured_output(_AccoResult, method="function_calling")
    payload = {"overnight_days": nights, "level": level,
               "daily_centers": daily_centers or [], "hotel_pool": pool}
    result = await llm.ainvoke([SystemMessage(content=_SYS), HumanMessage(content=str(payload))], config=config)
    assignments = [{"day": a.day, "hotel": a.hotel.model_dump(by_alias=True)} for a in result.assignments]
    return attach_hotels(day_plans, assignments)


async def accommodation(state, config) -> dict:
    day_plans = state.get("day_plans", []) or []
    if not overnight_days(day_plans):
        return {}
    updated = await assign_hotels(day_plans, state.get("city", ""),
                                  state.get("preferences", {}) or {},
                                  state.get("daily_centers", []) or [], config)
    return {"day_plans": updated}
```

**(b)** 在 `backend/app/planning/apply.py` import 区追加：
```python
from app.graph.nodes.accommodation import assign_hotels
from app.graph.nodes.budget import compute_budget
```
在 `apply_operations` 的「`for d in touched: finalize`」之后、`needs_budget = ...` 计算后、组装 `out` 之前插入重算：
```python
    # 住宿重算：仅当本轮需要（set_hotel / replace_plan）
    if needs_accom and day_plans:
        city = (state.get("normalized_req", {}) or {}).get("city") or state.get("city", "")
        prefs = (state.get("normalized_req", {}) or {}).get("preferences") or state.get("preferences", {}) or {}
        day_plans = await assign_hotels(day_plans, city, prefs, centers, config)

    # 预算重算：仅当本轮需要且能确定 limit
    budget_check = None
    limit = budget_new if budget_new is not None else state.get("budget")
    if needs_budget and limit:
        num_people = (state.get("normalized_req", {}) or {}).get("num_people") or state.get("num_people", 1) or 1
        bc = compute_budget(day_plans, num_people, float(limit), state.get("retry_count", 0) or 0)
        budget_check = bc["budget_check"]
```
并把 `out` 字典在 `if budget_new is not None:` 之前补：
```python
    if budget_check is not None:
        out["budget_check"] = budget_check
```

> 注：apply 不做 plan_new 的「超支回退重排」自循环（原 `route_after_budget` 的 itinerary↺）。线性图无回退边；预算超支由 render 诚实告知 + budget_check.over 标志体现。这是设计「0 条件边」的有意取舍，记入 Self-Review 偏差。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_apply_recompute.py tests/test_accommodation.py -q`
Expected: PASS（test_accommodation 既有用例仍绿——节点行为不变；新用例 2 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/accommodation.py backend/app/planning/apply.py backend/tests/test_apply_recompute.py
git commit -m "feat(linear): apply 接入住宿(assign_hotels)+预算(compute_budget)重算

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## 阶段 3：4 单元节点 + 切图（一次性换拓扑）

> 阶段 3 完成后系统切到新拓扑。Task 7-10 新增节点（旧图仍在、不引用新节点，回归仍绿）；Task 11 一次性换 builder/constants/stream + 拓扑测试。

### Task 7: understand 单元节点（dispatch_agent + clarify + preflight 三合一）

**Files:**
- Create: `backend/app/graph/nodes/understand.py`
- Test: `backend/tests/test_understand.py`

**Interfaces:**
- Consumes：`app.graph.nodes.dispatch_agent` 的纯 helper（`_rule_based_intent`/`IntentResult`/`_parse_refine_llm`/`_INTENT_SYS`）、`app.graph.nodes.dispatch.NormalizedReq`/`_SYS`、`app.graph.nodes.clarify`（`_evaluate_gaps`/`_apply_answer`）、`app.planning.preflight.preflight`、`app.core.constants.MAX_CLARIFY_ROUNDS`、`langgraph.types.interrupt`、`build_llm`
- Produces：`async def understand(state: dict, config) -> dict`
  - 返回 `{"operations": list[dict], "last_intent": str, "normalized_req": dict, ...顶层需求字段}`；qa→`operations=[{op:answer_only,question}]`；refine 无法解析→透传 `refine_clarification` 走 answer_only；plan_new→`operations=[{op:replace_plan,requirements_patch:req}]`，需求缺口在节点内多轮 interrupt 澄清

- [ ] **Step 1: 写失败测试**

`backend/tests/test_understand.py`：
```python
import pytest

from app.graph.nodes.understand import understand
from app.graph.nodes.dispatch_agent import IntentResult
from app.graph.nodes.refine_ops import RefinePlan, Operation
from app.graph.nodes.dispatch import NormalizedReq
from tests.conftest import make_fake_build_llm


def _plan():
    return [{"day": 1, "items": [{"type": "attraction", "name": "越秀公园"}]}]


async def test_qa_produces_answer_only(monkeypatch):
    # 无 plan 时规则判定为 plan_new；要测 qa，给 has_plan 且问句
    out = await understand({"query": "第二天为什么这么赶？", "day_plans": _plan()}, None)
    assert out["last_intent"] == "qa"
    assert out["operations"][0]["op"] == "answer_only"
    assert out["operations"][0]["question"] == "第二天为什么这么赶？"


async def test_refine_produces_operations_with_preflight_patch(monkeypatch):
    plan = RefinePlan(operations=[Operation(op="set_region", day=1, area="黄埔")])
    monkeypatch.setattr("app.graph.nodes.understand.build_llm", make_fake_build_llm(structured=plan))
    out = await understand(
        {"query": "把第一天改成黄埔", "day_plans": _plan(),
         "normalized_req": {"city": "广州"}}, None)
    assert out["last_intent"] == "refine_existing"
    op = out["operations"][0]
    assert op["op"] == "set_region" and op["requirements_patch"]["city"] == "广州"


async def test_refine_unparseable_routes_to_answer_only(monkeypatch):
    plan = RefinePlan(operations=[], clarification="你想把第几天换到哪里？")
    monkeypatch.setattr("app.graph.nodes.understand.build_llm", make_fake_build_llm(structured=plan))
    out = await understand({"query": "改一下那个", "day_plans": _plan()}, None)
    assert out["last_intent"] == "qa"
    assert out["operations"][0]["op"] == "answer_only"
    assert out["refine_clarification"].startswith("你想")


async def test_plan_new_no_gaps_produces_replace_plan(monkeypatch):
    norm = NormalizedReq(city="广州", days=3, num_people=2, budget=5000.0)
    monkeypatch.setattr("app.graph.nodes.understand.build_llm", make_fake_build_llm(structured=norm))
    # 无缺口：桩 _evaluate_gaps 返回空
    monkeypatch.setattr("app.graph.nodes.understand._evaluate_gaps",
                        _async_return([]))
    out = await understand({"query": "去广州玩3天"}, None)   # 无 day_plans → plan_new
    assert out["last_intent"] == "plan_new"
    op = out["operations"][0]
    assert op["op"] == "replace_plan"
    assert op["requirements_patch"]["city"] == "广州" and op["requirements_patch"]["days"] == 3
    assert out["city"] == "广州"


def _async_return(value):
    async def _f(*a, **k):
        return value
    return _f
```

> 说明：`_async_return` 桩 `_evaluate_gaps` 避免触发 interrupt（interrupt 需图上下文）。plan_new 的多轮 interrupt 澄清由阶段 4 的 e2e（走 `build_graph` + `Command(resume=...)`，参考 `test_clarify_interrupt.py`）覆盖。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_understand.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.graph.nodes.understand'`）

- [ ] **Step 3: 写实现**

创建 `backend/app/graph/nodes/understand.py`：
```python
"""understand 单元节点（线性图 1/4）：dispatch_agent + clarify + preflight 三合一。

职责：
1. 判意图（复用 dispatch_agent._rule_based_intent + LLM 兜底）。
2. 解析 operations：plan_new→replace_plan；refine→ops（LLM）；qa→answer_only。
3. plan_new 需求澄清：节点内 while + interrupt 多轮（复用 clarify._evaluate_gaps/_apply_answer）。
4. preflight 闸门：补救可补字段（city/days）；可由用户补的缺口 → 单次 interrupt 反问。

⚠️ interrupt 前的所有 LLM 评估在 resume 时会重跑，必须 temperature=0 保持确定性（同 clarify）。
"""
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt

from app.core.constants import MAX_CLARIFY_ROUNDS
from app.graph.nodes.dispatch import NormalizedReq, _SYS as _DISPATCH_SYS
from app.graph.nodes.dispatch_agent import (
    IntentResult, _rule_based_intent, _parse_refine_llm, _INTENT_SYS,
)
from app.graph.nodes.clarify import _evaluate_gaps, _apply_answer
from app.planning.preflight import preflight
from app.llm.factory import build_llm


async def _llm_intent(state: dict, query: str, config) -> IntentResult:
    llm = build_llm(temperature=0).with_structured_output(IntentResult, method="function_calling")
    result = await llm.ainvoke([
        SystemMessage(content=_INTENT_SYS),
        HumanMessage(content=str({
            "query": query,
            "conversation_summary": state.get("conversation_summary", ""),
            "normalized_req": state.get("normalized_req", {}) or {},
            "has_day_plans": bool(state.get("day_plans")),
        })),
    ], config=config)
    if result.confidence < 0.55:
        result.intent = "qa"
    return result


async def _normalize_req(state: dict, query: str, config) -> dict:
    llm = build_llm(temperature=0).with_structured_output(NormalizedReq, method="function_calling")
    memory = state.get("memory_context", {}) or {}
    req = await llm.ainvoke([
        SystemMessage(content=_DISPATCH_SYS),
        HumanMessage(content=str({
            "当前用户消息": query,
            "会话摘要": state.get("conversation_summary", ""),
            "最近消息": memory.get("recent_messages", []),
            "当前结构化需求": state.get("normalized_req", {}) or {},
        })),
    ], config=config)
    return req.model_dump()


async def understand(state: dict, config=None) -> dict:
    query = state.get("query", "")
    has_plan = bool(state.get("day_plans"))
    result = _rule_based_intent(query, has_plan) or await _llm_intent(state, query, config)

    # —— qa ——
    if result.intent == "qa":
        return {"operations": [{"op": "answer_only", "question": query}], "last_intent": "qa"}

    # —— refine ——
    if result.intent == "refine_existing":
        plan = await _parse_refine_llm(state, query, result.target_day, config)
        if not plan.operations and plan.clarification:
            return {"operations": [{"op": "answer_only", "question": query}],
                    "last_intent": "qa", "refine_clarification": plan.clarification}
        operations = [o.model_dump() for o in plan.operations]
        req = dict(state.get("normalized_req", {}) or {})
        res = preflight(operations, {**state, "normalized_req": req})
        if res.clarification:
            ans = interrupt({"field": "city", "question": res.clarification, "options": []})
            req["city"] = ans.strip() if isinstance(ans, str) else req.get("city", "")
            res = preflight(operations, {**state, "normalized_req": req})
        return {"operations": res.operations, "last_intent": "refine_existing", "normalized_req": req}

    # —— plan_new ——
    norm = await _normalize_req(state, query, config)
    req = {**(state.get("normalized_req", {}) or {}), **norm}
    history: list[dict] = list(state.get("clarify_history", []) or [])
    rnd = 0
    while rnd < MAX_CLARIFY_ROUNDS:
        gaps = await _evaluate_gaps({**state, "query": query, "clarify_history": history}, config)
        if not gaps:
            break
        g = gaps[0]
        ans = interrupt({"field": g.field, "question": g.question, "options": g.options})
        patch = _apply_answer(g.field, ans, {"normalized_req": req})
        req = patch["normalized_req"]
        history.append({"field": g.field, "question": g.question, "options": g.options, "answer": ans})
        rnd += 1

    operations = [{"op": "replace_plan", "requirements_patch": req}]
    res = preflight(operations, {**state, "normalized_req": req})
    top = {k: req[k] for k in ("city", "start_date", "days", "num_people", "budget") if k in req}
    return {"operations": res.operations, "last_intent": "plan_new",
            "normalized_req": req, "clarified": True, **top}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_understand.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/understand.py backend/tests/test_understand.py
git commit -m "feat(linear): understand 节点（意图解析+operations+preflight+多轮interrupt澄清）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: collect_context 单元节点（薄壳）

**Files:**
- Create: `backend/app/graph/nodes/collect_context.py`
- Test: `backend/tests/test_collect_context_node.py`

**Interfaces:**
- Consumes：`app.planning.context.collect_context`（Task 3）；`state["operations"]`（Task 7 产出）
- Produces：`async def collect_context_node(state: dict, config=None) -> dict` → `{"context": dict}`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_collect_context_node.py`：
```python
from app.graph.nodes.collect_context import collect_context_node


async def test_node_wraps_context_under_key(fake_amap):
    fake_amap["search_poi"] = [{"name": "越秀公园", "poi_id": "G1"}]
    out = await collect_context_node(
        {"operations": [{"op": "replace_plan", "requirements_patch": {"city": "广州", "days": 2}}],
         "normalized_req": {"city": "广州"}}, None)
    assert "context" in out
    assert out["context"]["attractions"][0]["name"] == "越秀公园"


async def test_node_local_op_empty_context(fake_amap):
    out = await collect_context_node({"operations": [{"op": "reorder", "day": 1}]}, None)
    assert out["context"]["attractions"] == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_collect_context_node.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写实现**

创建 `backend/app/graph/nodes/collect_context.py`：
```python
"""collect_context 单元节点（线性图 2/4）：薄壳，调 app.planning.context.collect_context。"""
from app.planning.context import collect_context


async def collect_context_node(state: dict, config=None) -> dict:
    ctx = await collect_context(state.get("operations") or [], state, config)
    return {"context": ctx}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_collect_context_node.py -q`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/collect_context.py backend/tests/test_collect_context_node.py
git commit -m "feat(linear): collect_context 单元节点（薄壳）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: apply 单元节点（薄壳 + refine_notes 包装）

**Files:**
- Create: `backend/app/graph/nodes/apply_node.py`
- Test: `backend/tests/test_apply_node.py`

**Interfaces:**
- Consumes：`app.planning.apply.apply_operations`（Task 5/6）；`state["operations"]`/`state["context"]`
- Produces：`async def apply_node(state: dict, config=None) -> dict`
  - 把 `apply_operations` 的 `applied`/`skipped` 包成 `refine_notes={applied,skipped}`（供 render 复用 summarize 的 notes 逻辑），其余 key 原样写 state

- [ ] **Step 1: 写失败测试**

`backend/tests/test_apply_node.py`：
```python
from app.graph.nodes.apply_node import apply_node
from app.graph.nodes.itinerary import insert_transport


def _plan():
    day1 = [{"type": "attraction", "name": "A", "poi_id": "B1", "location": {"lng": 104.05, "lat": 30.65}},
            {"type": "meal", "name": "饭", "poi_id": "M1", "location": {"lng": 104.06, "lat": 30.66}}]
    return [{"day": 1, "items": insert_transport(day1), "center": {"lng": 104.055, "lat": 30.655}}]


async def test_apply_node_wraps_refine_notes():
    out = await apply_node(
        {"operations": [{"op": "reorder", "day": 1, "strategy": "reverse"}],
         "context": {}, "day_plans": _plan(), "plan_version": 1}, None)
    assert "refine_notes" in out
    assert out["refine_notes"]["applied"]
    assert "applied" not in out and "skipped" not in out   # 已收进 refine_notes
    assert out["changed_days"] == [1]


async def test_apply_node_answer_only_noop():
    out = await apply_node(
        {"operations": [{"op": "answer_only", "question": "为什么"}],
         "context": {}, "day_plans": _plan(), "plan_version": 1}, None)
    assert out["changed_days"] == [] and out["plan_version"] == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_apply_node.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写实现**

创建 `backend/app/graph/nodes/apply_node.py`：
```python
"""apply 单元节点（线性图 3/4）：薄壳，调 app.planning.apply.apply_operations。

把执行器的 applied/skipped 收进 refine_notes（render 据此诚实回报），其余字段原样写 state。
"""
from app.planning.apply import apply_operations


async def apply_node(state: dict, config=None) -> dict:
    res = await apply_operations(state.get("operations") or [],
                                 state.get("context") or {}, state, config)
    applied = res.pop("applied", [])
    skipped = res.pop("skipped", [])
    res["refine_notes"] = {"applied": applied, "skipped": skipped}
    return res
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_apply_node.py -q`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/apply_node.py backend/tests/test_apply_node.py
git commit -m "feat(linear): apply 单元节点（薄壳 + refine_notes 包装）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: render 单元节点（summarize + answer 合一，流式，诚实回报）

**Files:**
- Create: `backend/app/graph/nodes/render.py`
- Test: `backend/tests/test_render.py`

**Interfaces:**
- Consumes：`build_llm`；`state`（`operations`/`day_plans`/`refine_notes`/`refine_clarification`/`conversation_summary`/`budget_check`/`dropped_attractions`）
- Produces：`async def render(state: dict, config=None) -> dict` → `{"summary": str}`（攻略/QA 均 `build_llm().astream(...)` 流式；clarification 直接返回不调 LLM）
  - token 流式靠 `metadata.langgraph_node == "render"`（Task 11 改 stream.py）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_render.py`：
```python
from app.graph.nodes.render import render
from tests.conftest import make_fake_build_llm


async def test_render_clarification_verbatim_no_llm(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("澄清分支不应调用 LLM")
    monkeypatch.setattr("app.graph.nodes.render.build_llm", _boom)
    out = await render({"refine_clarification": "你想把第几天换到哪里？"}, None)
    assert out["summary"] == "你想把第几天换到哪里？"


async def test_render_summary_streams_day_plans(monkeypatch):
    monkeypatch.setattr("app.graph.nodes.render.build_llm", make_fake_build_llm(tokens=["成都", "攻略"]))
    out = await render({"operations": [{"op": "reorder", "day": 1}],
                        "day_plans": [{"day": 1, "items": []}],
                        "refine_notes": {"applied": ["第1天顺序已调整"], "skipped": []}}, None)
    assert out["summary"] == "成都攻略"


async def test_render_answer_only_streams_qa(monkeypatch):
    monkeypatch.setattr("app.graph.nodes.render.build_llm", make_fake_build_llm(tokens=["回答"]))
    out = await render({"operations": [{"op": "answer_only", "question": "为什么"}],
                        "day_plans": [{"day": 1, "items": []}],
                        "conversation_summary": "成都3天"}, None)
    assert out["summary"] == "回答"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_render.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写实现**

创建 `backend/app/graph/nodes/render.py`：
```python
"""render 单元节点（线性图 4/4）：summarize + answer 合一。

- refine_clarification（understand 透传无法解析的反问）→ 原样返回，不调 LLM。
- answer_only / 无 day_plans → 基于会话与现有方案回答（流式）。
- 有 day_plans → 渲染逐日攻略（流式）+ 诚实回报 refine_notes 里的 skipped。

⚠️ 必须 async + astream(..., config=config)，token 才能冒泡；stream.py 放行 langgraph_node=="render"。
"""
from langchain_core.runnables import RunnableConfig

from app.llm.factory import build_llm

_SUMMARY_SYS = "你是旅行攻略撰写助手。请用简体中文，按天输出清晰、可读的逐日行程攻略，语气友好实用。"
_ANSWER_SYS = ("你是旅行助手。只基于当前会话摘要和已有行程回答用户问题，不要重新规划或修改 day_plans。"
               "若用户问及某景点为何未安排，可参考 dropped_attractions（含未排入景点及原因）说明。")


def _question(state: dict) -> str:
    for op in state.get("operations") or []:
        if op.get("op") == "answer_only":
            return op.get("question") or state.get("query", "")
    return state.get("query", "")


async def render(state: dict, config: RunnableConfig = None) -> dict:
    clar = state.get("refine_clarification")
    if clar:
        return {"summary": clar}

    operations = state.get("operations") or []
    is_answer = any(o.get("op") == "answer_only" for o in operations)
    day_plans = state.get("day_plans") or []

    if is_answer or not day_plans:
        sys = _ANSWER_SYS
        user = str({
            "question": _question(state),
            "conversation_summary": state.get("conversation_summary", ""),
            "day_plans": day_plans,
            "budget": state.get("budget_check", {}) or {},
            "dropped_attractions": state.get("dropped_attractions", []) or [],
        })
    else:
        notes = state.get("refine_notes") or {}
        extra = (f"\n本轮修改记录（applied/skipped）：{notes}"
                 f"\n若有 skipped 项，请如实简述未能完成的部分。") if notes else ""
        sys = _SUMMARY_SYS
        user = f"请根据以下结构化逐日行程，写成中文攻略：\n{day_plans}{extra}"

    parts: list[str] = []
    async for chunk in build_llm().astream(
        [{"role": "system", "content": sys}, {"role": "user", "content": user}],
        config=config,
    ):
        if chunk.content:
            parts.append(chunk.content)
    return {"summary": "".join(parts)}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_render.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/render.py backend/tests/test_render.py
git commit -m "feat(linear): render 节点（攻略/QA 合一流式 + 澄清原样 + 诚实回报）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: 切图为 6 节点直线 + constants NODES + stream token 放行

**Files:**
- Modify: `backend/app/graph/state.py`（TripState 新增 `operations`/`context`）
- Modify: `backend/app/graph/builder.py`（重写为 6 节点 0 条件边）
- Modify: `backend/app/core/constants.py`（NODES/NODE_LABELS 改为 6 单元）
- Modify: `backend/app/graph/stream.py`（token 放行 `=="render"`）
- Test: Create `backend/tests/test_linear_topology.py`；Modify `backend/tests/test_contracts.py`（NODES 等值断言）；Modify `backend/tests/test_builder.py`（拓扑断言重写）

**Interfaces:**
- Consumes：Task 7-10 的 4 个节点 + `memory`/`memory_update`
- Produces：`build_graph(checkpointer=None)` / `make_graph()` 编译出 `START→memory→understand→collect_context→apply→render→memory_update→END` 直线图

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_linear_topology.py`：
```python
from app.graph.builder import build_graph


def test_linear_topology_six_nodes_no_conditional():
    g = build_graph()._graph if hasattr(build_graph(), "_graph") else None
    # 直接查编译前结构更稳：用 get_graph()
    drawable = build_graph().get_graph()
    names = {n.id for n in drawable.nodes.values()} if hasattr(drawable, "nodes") else set()
    for expected in ("memory", "understand", "collect_context", "apply", "render", "memory_update"):
        assert expected in names
    # 旧节点不应存在
    for gone in ("dispatch_agent", "clarify", "retrieve", "weather", "attractions",
                 "restaurants", "transport", "enrich_duration", "itinerary",
                 "accommodation", "budget", "refine", "answer", "summarize"):
        assert gone not in names
```

> 实现 Step 3 前先 `uv run python -c "from app.graph.builder import build_graph; print(build_graph().get_graph())"` 确认 `get_graph()` 的节点访问形态，按真实 API 调整断言取节点名的方式（LangGraph `get_graph().nodes` 为 dict）。

修改 `backend/tests/test_contracts.py:24` 的 NODES 等值断言为：
```python
    assert NODES == {"memory", "understand", "collect_context", "apply", "render", "memory_update"}
```

`backend/tests/test_builder.py` 中依赖旧拓扑（节点数/边）的断言整体重写为新直线断言（用 `get_graph()` 验证 6 节点 + START→memory→understand→...→memory_update→END 的边链；删除对 conditional_edges 的断言）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_linear_topology.py tests/test_contracts.py tests/test_builder.py -q`
Expected: FAIL（旧 builder 仍 17 节点；NODES 仍 15 项）

- [ ] **Step 3: 写实现**

**(a)** `backend/app/graph/state.py` 在 TripState「并行检索产出」段之前新增（线性图单元间传值）：
```python
    # —— 线性编排：单元间传值 ——
    operations: list           # understand 解析出的有序原子操作
    context: dict              # collect_context 预取的数据（weather/attractions/restaurants）
```

**(b)** 重写 `backend/app/graph/builder.py`：
```python
"""图构建（线性化）：START → memory → understand → collect_context → apply → render → memory_update → END。

6 节点 0 条件边：从左读到右即执行顺序。understand 内用 interrupt 做需求澄清/可行性反问；
collect_context 按 operations 类型并发取数；apply 执行 operations 并重算住宿/预算；render 出话。
"""
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.graph.state import TripState
from app.graph.nodes.memory import memory
from app.graph.nodes.understand import understand
from app.graph.nodes.collect_context import collect_context_node
from app.graph.nodes.apply_node import apply_node
from app.graph.nodes.render import render
from app.graph.nodes.memory_update import memory_update


def _build_state_graph():
    g = StateGraph(TripState)
    for name, fn in [
        ("memory", memory),
        ("understand", understand),
        ("collect_context", collect_context_node),
        ("apply", apply_node),
        ("render", render),
        ("memory_update", memory_update),
    ]:
        g.add_node(name, fn)
    g.add_edge(START, "memory")
    g.add_edge("memory", "understand")
    g.add_edge("understand", "collect_context")
    g.add_edge("collect_context", "apply")
    g.add_edge("apply", "render")
    g.add_edge("render", "memory_update")
    g.add_edge("memory_update", END)
    return g


def build_graph(checkpointer=None):
    """本地 / 测试入口：默认用 MemorySaver。"""
    return _build_state_graph().compile(checkpointer=checkpointer or MemorySaver())


def make_graph():
    """LangGraph API/Platform 入口：不传 checkpointer，由平台自动注入持久化。"""
    return _build_state_graph().compile()
```

**(c)** `backend/app/core/constants.py` 把 NODES / NODE_LABELS 替换为：
```python
NODES = {"memory", "understand", "collect_context", "apply", "render", "memory_update"}

NODE_LABELS = {
    "memory": "正在读取会话上下文…",
    "understand": "正在理解你的需求…",
    "collect_context": "正在检索景点/餐饮/天气…",
    "apply": "正在编排行程…",
    "render": "正在生成攻略…",
    "memory_update": "正在保存会话记忆…",
}
```

**(d)** `backend/app/graph/stream.py:49` 把 token 放行节点名改为 `render`：
```python
            elif kind == "on_chat_model_stream" and ev.get("metadata", {}).get("langgraph_node") == "render":
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_linear_topology.py tests/test_contracts.py tests/test_builder.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/state.py backend/app/graph/builder.py backend/app/core/constants.py backend/app/graph/stream.py backend/tests/test_linear_topology.py backend/tests/test_contracts.py backend/tests/test_builder.py
git commit -m "feat(linear): 切图为 6 节点 0 条件边直线 + NODES/token 放行 render

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## 阶段 4：迁移测试 + 前端进度

### Task 12: 迁移 e2e / 多轮 / stream 测试至新链路

**Files:**
- Modify: `backend/tests/test_chat_stream.py`、`test_chat_stream_m2.py`、`test_chat_stream_m4.py`（走新链路；node 名改为新单元名）
- Modify: `backend/tests/test_multiturn_replan.py`、`test_multiturn_refine.py`、`test_multiturn_qa.py`、`test_m5fix_e2e.py`（e2e：打桩 `understand.build_llm` 为对应 NormalizedReq/RefinePlan/IntentResult）
- Modify: `backend/tests/test_clarify_interrupt.py`（interrupt 现由 understand 抛出；走 understand）
- Modify: `backend/tests/test_sqlite_checkpointer.py`（多轮持久化经新链路）
- Test: 受影响文件各自 + 全量 `cd backend && uv run pytest -q`

**Interfaces:** Consumes 阶段 1-3 全部产出；无新接口，仅迁移。

- [ ] **Step 1: 逐文件迁移（每改一个文件即跑该文件）**

迁移规则（对每个 e2e）：
- 把 `monkeypatch.setattr(dispatch_agent, "build_llm", ...)` 改为 `monkeypatch.setattr("app.graph.nodes.understand.build_llm", ...)`（understand 现承载意图/标准化/refine 解析的 LLM 调用）。
- plan_new e2e：桩 understand.build_llm 为 `make_fake_build_llm(structured=NormalizedReq(...))`；若该 e2e 还断言中间节点名（`weather`/`itinerary`/`summarize` 等 SSE node_start），改为新单元名（`collect_context`/`apply`/`render`）。
- refine e2e：桩 understand.build_llm 为 `make_fake_build_llm(structured=RefinePlan(operations=[...]))`；旧断言 `route_after_*` 行为的，删除（路由已无条件边），改断言最终 `day_plans`/`changed_days`/`plan_version`。
- QA e2e：has_plan + 问句 → 规则判 qa，无需桩 LLM（除非 render 流式断言 token，则桩 `render.build_llm` 为 `make_fake_build_llm(tokens=[...])`）。
- `test_clarify_interrupt.py`：interrupt payload 现由 understand 抛出，走 `build_graph` + `astream` + `Command(resume=...)` 不变；只把「期望在 clarify 节点暂停」改为「在 understand 暂停」（SSE clarify 事件读取逻辑不变，仍 `aget_state().tasks[].interrupts[0].value`）。需桩 understand 的 `_evaluate_gaps` 或 `build_llm`（ClarifyGaps）以产生一个 gap。
- token 流断言：凡断言 summarize 产 token 的，节点名改 `render`（stream.py 已放行 render）。

> 每个 e2e 改完立即 `uv run pytest tests/<file> -q`；红了用 systematic-debugging，不弱化断言（保留精确等值/分天断言，对齐新设计正确行为）。

- [ ] **Step 2: 全量回归**

Run: `cd backend && uv run pytest -q`
Expected: 全绿（仅余既有第三方 Starlette/Swig 弃用告警）。剩余红测分两类处理：
- 仍 import 旧节点符号（`weather`/`attractions`/`route_after_*`/`dispatch_agent` 等）的测试 → 归入 Task 14 一并处理（这些测试测的是阶段 5 才降级的旧节点）。
- 断言旧行为的 e2e → 本任务按新链路迁移。

- [ ] **Step 3: 提交**

```bash
git add backend/tests/
git commit -m "test(linear): 迁移 e2e/多轮/stream/clarify 测试至 6 节点新链路

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: 前端进度标签四档

**Files:**
- Modify: `frontend/src/components/AgentProgress.vue`（或承载 node label 映射的文件；先 `rg -l "正在按顺路编排|node_start|NODE" frontend/src` 定位）
- Test: `cd frontend && npx vue-tsc -b`（类型门禁）+ 手测 SSE 进度

**Interfaces:** Consumes 后端 `node_start` 事件的新 node 名（understand/collect_context/apply/render）。

- [ ] **Step 1: 定位前端进度映射**

Run: `rg -n "node_start|understand|collect_context|正在|stage|progress" frontend/src/components frontend/src/types`
读出前端如何把 `node_start.node` 映射成进度文案/阶段。

- [ ] **Step 2: 改四档映射**

把前端的节点→文案映射改为认 6 个新 node 名（至少 understand/collect_context/apply/render 四个业务档；memory/memory_update 可隐藏或归入「准备/收尾」）。旧节点名映射保留兼容（不删，避免历史会话回放断裂）。具体 diff 依 Step 1 实际结构而定：在映射对象里新增：
```ts
understand: '正在理解你的需求…',
collect_context: '正在检索景点/餐饮/天气…',
apply: '正在编排行程…',
render: '正在生成攻略…',
```

- [ ] **Step 3: 类型门禁**

Run: `cd frontend && npx vue-tsc -b`
Expected: 通过（无类型错误）

- [ ] **Step 4: 提交**

```bash
git add frontend/src
git commit -m "feat(linear): 前端进度标签适配 6 节点新链路（四业务档）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## 阶段 5：清理旧节点 + state 瘦身

### Task 14: 旧节点降级为 helper 模块 / 删除无引用节点 + 迁移剩余测试

**Files:**
- Modify（删节点函数、保留纯 helper）：`dispatch_agent.py`（删 `dispatch_agent`/`route_after_dispatch`/`reset_for_plan_new`，保留 `_rule_based_intent`/`_parse_refine_llm`/`IntentResult`/`_day_plans_digest`/`_INTENT_SYS`/`_REFINE_SYS`/`_target_day`/`_rule_*`）、`clarify.py`（删 `clarify`/`route_after_clarify`，保留 `_evaluate_gaps`/`_apply_answer`/`Gap`/`ClarifyGaps`/`_SYS`）、`refine.py`（删 `refine` 节点函数，保留全部 `_*` helper）、`accommodation.py`（删 `accommodation` 节点函数，保留 `assign_hotels`/`attach_hotels`/`overnight_days`/`hotel_keyword`/模型）、`budget.py`（删 `budget`/`route_after_budget`，保留 `compute_budget`/`_sum_costs`/`_pick_cut_suggestions`）、`itinerary.py`（删 `itinerary` 节点函数，**保留全部 re-export** + `_distance_cache_path`）
- Delete（确认无引用后物理删除）：`weather.py`、`attractions.py`、`restaurants.py`、`transport.py`、`enrich_duration.py`、`retrieve.py`、`routing.py`、`answer.py`、`summarize.py`
- Modify/Delete tests：删除/迁移仅测已删节点的测试（`test_parallel_retrieval.py`→改测 `collect_context`；`test_need_routing.py`/`test_refine_wiring.py`→删（路由已无条件边）；`test_dispatch_agent.py`→改测 `understand` 或删重复用例；`test_enrich_duration.py`→保留（`apply_durations` 若仍被 soft_fill/itinerary 用则留，否则删）；`test_summarize.py`/`test_answer_dropped.py`→改测 `render`；`test_refine_node.py`/`test_refine_search.py`/`test_refine_region.py`/`test_refine_transport.py`/`test_refine_budget.py`/`test_refine_helpers.py`→改 `from ...refine import refine` 为 `from app.planning.apply import apply_operations`，refine helper import 不变）
- Test: 全量 `cd backend && uv run pytest -q`

**Interfaces:** 无新接口；删除 + 迁移 + 回归。

- [ ] **Step 1: 删前确认引用**

Run（逐个确认旧节点函数无生产引用，只剩测试）：
```bash
cd backend && rg -n "route_after_plan|route_after_accommodation|route_after_budget|route_after_dispatch|route_after_clarify|reset_for_plan_new|\bdispatch_agent\b|\.weather import|\.attractions import|\.restaurants import|\.transport import|enrich_duration|\.retrieve import|nodes.answer import|nodes.summarize import|nodes.routing import" app
```
Expected: 仅 `app/graph/nodes/*` 内部互引（将随本任务清理）；`app/graph/builder.py` 已不引用（阶段 3 切图后）。若 `app` 下仍有生产引用，先消除再删。

- [ ] **Step 2: 降级节点函数 + 删除无引用文件**

- 对「降级」类文件：删除其图节点函数本体与路由函数，文件保留纯 helper（顶部 docstring 补一行「本模块已降级为 helper 库，不再注册为图节点」）。
- 对「删除」类文件：`git rm` 之；删除后 `rg` 再确认零引用。

- [ ] **Step 3: 迁移剩余测试**

按上方 tests 清单逐文件改：
- `test_parallel_retrieval.py`：删对 weather/attractions/restaurants/transport 节点的 import 与调用，改为 `from app.planning.context import collect_context` 测并发取数（replace_plan 全量、局部空）。
- `test_dispatch_agent.py`：保留仍存在的 helper 用例（`_rule_based_intent`/`_parse_refine_llm`/`IntentResult`）；删除测 `dispatch_agent`/`route_after_dispatch`/`reset_for_plan_new` 的用例（已迁至 `test_understand.py`）。
- `test_need_routing.py`、`test_refine_wiring.py`：`git rm`（路由条件边已删，断言对象不存在）。
- `test_summarize.py`、`test_answer_dropped.py`：改 import 与调用为 `render`（攻略含 dropped 的断言改在 render 的攻略 payload 上验证）。
- `test_refine_node.py` 等 refine 系列：把 `from app.graph.nodes.refine import refine` 改为 `from app.planning.apply import apply_operations`，并把 `await refine(state)` 改为 `await apply_operations(state["refine_request"]["operations"], {}, state)`；helper 直接 import 的用例（`_relax_stops`/`_finalize_day`/`_find_day` 等）不变。断言对齐 `apply_operations` 输出键（`refine_notes` 改由调用方包装——这些测试直接调 `apply_operations`，故读 `out["applied"]`/`out["skipped"]`，不是 `refine_notes`）。

- [ ] **Step 4: 全量回归**

Run: `cd backend && uv run pytest -q`
Expected: 全绿（仅余既有第三方告警）。

- [ ] **Step 5: 提交**

```bash
git add -A backend
git commit -m "refactor(linear): 旧节点降级为 helper / 删除无引用节点 + 迁移剩余测试

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 15: state 瘦身（移除纯中间态字段）

**Files:**
- Modify: `backend/app/graph/state.py`（移除已无跨轮持久化价值的中间态字段）
- Test: 全量 `cd backend && uv run pytest -q`

**Interfaces:** 无新接口；仅删 state 字段并确认无残留读写。

- [ ] **Step 1: 确认字段无残留引用**

Run（确认这些纯中间态字段在 `app` 生产代码中已无读写，仅可能存在于测试）：
```bash
cd backend && rg -n "\bweather\b|\battractions\b|\brestaurants\b|\btransport\b|daily_centers|relax_level|retry_count|refine_request" app/graph app/services
```
对每个字段判定：仍被 apply/context/render 以**局部变量或 context 子键**使用的（如 `context['weather']`、`daily_centers` 作 apply 返回）保留在 state；仅旧节点用过、现已无 state 读写的移除。

- [ ] **Step 2: 移除字段**

从 `TripState` 移除经 Step 1 确认无 state 级读写的字段（候选：`weather`/`attractions`/`restaurants`/`transport`/`relax_level`/`retry_count`/`budget_advice`，以及旧 `refine_request` 若 understand/apply 已不写）。
**保留**（需跨轮持久化或仍被读写）：`messages`/`conversation_summary`/`memory_context`/`normalized_req`/`day_plans`/`daily_centers`/`budget_check`/`plan_version`/`changed_days`/`clarify_history`/`clarified`/`clarify_round`/`dropped_attractions`/`refine_notes`/`refine_clarification`/`operations`/`context`/`last_intent`/`active_plan_id`/`city`/`start_date`/`days`/`num_people`/`preferences`/`budget`/`summary`/`query`。
> 删字段务必保守：TypedDict total=False，多删一个被读的字段会静默丢值。每删一个跑一次全量。

- [ ] **Step 3: 全量回归**

Run: `cd backend && uv run pytest -q`
Expected: 全绿。

- [ ] **Step 4: 提交**

```bash
git add backend/app/graph/state.py
git commit -m "refactor(linear): state 瘦身，移除纯中间态字段

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage（逐节核对设计 `2026-06-24-orchestration-linear-simplify-design.md`）**
- §3.1 拓扑 6 节点 0 条件边：Task 11（builder 重写）✓
- §3.2 图节点 vs 普通函数边界：能力函数化 Task 3-6（planning/context/apply）+ 旧节点降级 Task 14 ✓
- §4 单元职责：understand(T7)=dispatch+clarify+preflight；collect_context(T8/T3)；apply(T9/T5/T6)=itinerary+refine+accommodation+budget；render(T10)=summarize+answer ✓
- §5 operations 统一模型：T1（replace_plan/answer_only/requirements_patch/question）+ understand 三链产 op（T7）✓
- §6 preflight 闸门：T2（依赖表+确定性校验+city 补救+裁决）+ understand interrupt 反问（T7）✓
- §7 apply 执行语义：T4（replace_plan 复用 OR-Tools）+ T5（局部 op 复用 refine + 收尾）+ T6（住宿/预算重算）+ 诚实回报 refine_notes（T9）✓
- §8 collect_context 按需取数：T3（replace_plan 全量并发；局部 op 由 refine handler 现场检索——见偏差①）✓
- §9 LangGraph 外壳 + SSE：interrupt 复用（T7）；checkpointer/make_graph 不动（T11 保留 build_graph/make_graph）；token 放行改 render（T11）；node 事件改 6 单元（T11+T13）✓
- §10 state 瘦身：第一阶段统一 normalized_req 入口（T2 infer_city/T7 写 normalized_req）+ 第二阶段删中间态（T15）✓
- §11 迁移五阶段：本计划阶段 1-5 一一对应 ✓
- §12 测试策略三层：schema(T1)、能力函数(T2-6)、单元+图(T7-12) ✓；关键用例「第一天改黄埔缺 city→反推/反问」= T2 `test_set_region_missing_city_asks_clarification` + T7 refine 分支 + 阶段4 e2e ✓
- §13 风险缓解：apply 拆 context/apply/preflight 文件 ✓；replace_plan 复用 OR-Tools 入口不重写 ✓；分阶段先函数化再切图 ✓；前端旧标签保留兼容（T13）✓；city 反推失败 fallback interrupt（T7）✓
- §14 非目标：未引 LLM 选工具、未删 LangGraph、未让 LLM 生成 day_plans、未改高德/算法/预算逻辑 ✓

**与设计的偏差（执行者须知，已在对应任务标注）**
- ① **collect_context 仅为 replace_plan 预取**：设计 §8 给了局部 op 的精细预取表，本计划让局部 op（add_poi/replace_poi/set_region）沿用现有 refine handler 的**现场检索**（`_search_insert`/`_set_region`），避免重写已测逻辑。设计 §8 精细预取表列为后续优化。功能等价（都「按需取数」），仅取数位置不同。
- ② **旧节点降级而非物理删除**：dispatch_agent/clarify/refine/itinerary/accommodation/budget 删图节点函数、**保留纯 helper**（被 understand/apply 复用 + 11+ 测试依赖 re-export）。仅 weather/attractions/restaurants/transport/enrich_duration/retrieve/routing/answer/summarize 物理删除。
- ③ **取消预算超支自循环重排**：旧 `route_after_budget` 的 `itinerary↺` 回退边在 0 条件边线性图中取消；预算超支由 `budget_check.over` + render 诚实告知体现（设计「0 条件边」的有意取舍）。

**Placeholder scan**：无 TBD/TODO；每个代码步含完整代码与确切命令/预期。集成性强的任务（T4 软填打桩、T11 get_graph 节点取名、T13 前端映射）显式标注「实现前先跑 X 确认真实形态再对齐」——这是确定性的前置校验指令，非占位。

**Type consistency**
- `Operation`（T1）新增 `requirements_patch: dict`/`question: str`，preflight（T2）`_check` 产出的 patch 写回 `op["requirements_patch"]`，understand（T7）/apply（T5）一致读取 ✓
- `apply_operations`（T5/T6）返回键 `day_plans/daily_centers/dropped_attractions/relax_level/changed_days/plan_version/applied/skipped/needs_accommodation/needs_budget_recheck/[budget]/[budget_check]`；apply_node（T9）把 `applied/skipped`→`refine_notes`，其余透传 ✓
- `replace_plan`（T4）返回 `daily_centers/day_plans/dropped_attractions/relax_level`，被 apply_operations（T5）解包一致 ✓
- `assign_hotels`（T6）签名 `(day_plans, city, preferences, daily_centers, config)`，apply（T6）与 accommodation 节点（T6）调用一致 ✓
- preflight `PreflightResult.operations/blocked/clarification`（T2）被 understand（T7）按字段读取一致 ✓
- render（T10）读 `refine_notes/refine_clarification/operations/day_plans`，与 apply_node（T9）/understand（T7）产出键一致 ✓
- NODES（T11 constants）== `test_contracts`（T11）断言集合 == builder（T11）注册节点名，三处同步 ✓
- token 放行 `langgraph_node=="render"`（T11 stream）== render 节点名（T10/T11）✓

