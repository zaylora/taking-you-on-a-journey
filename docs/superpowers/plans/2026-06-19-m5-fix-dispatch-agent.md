# M5 Fix：任务派发 Agent + 按需重排 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有 M5 编排从「intent + clarify + dispatch 三段 + refine 直连 budget + 住宿/预算每次必跑」重构为「单一 `dispatch_agent` 前置派发 + refine 局部重排 + 住宿/预算按 op 规则按需重排」，对齐最新架构图 [m5-graph-flow.excalidraw](../specs/m5-graph-flow.excalidraw)。

**Architecture:**
- **派发节点物理合并**：删除 `intent` 与 `dispatch` 两个节点，合并为单一 `dispatch_agent`（`START → memory → dispatch_agent`）。它一次性完成「判意图（plan_new / refine_existing / qa）+ 对 plan_new 标准化需求 + 对 refine 用规则解析出结构化 `RefineRequest`」。`clarify` 移到 `dispatch_agent` 之后、仅 plan_new 经过；`clarify` resume 时自己把澄清答案写回 `normalized_req` 及顶层字段（不再需要 clarify 后的二次标准化）。新增 pass-through 节点 `retrieve` 作为 4 个检索子 Agent 的 fan-out 锚点。
- **按需重排（规则路由，不调 LLM）**：`itinerary`（plan_new）与 `refine`（refine）出口共用 `route_after_plan`，按 `last_intent` + `refine_request.op` 三选一：`accommodation`（需重排酒店）/ `budget`（不重排酒店但需重算预算）/ `summarize`（都不需）。`accommodation` 出口用 `route_after_accommodation` 决定 `budget` / `summarize`。这对应图里「酒店需重排?」「预算需重算?」两个判断菱形。
- **refine 局部重排 + 选择性补检索**：`refine` 改为 async，按 `op` 在旧 `day_plans` 上**只改受影响的天**（保持 `changed_days` 精确，不回全量 `itinerary`）。`change_meal` / `add` / `replace` 需要新 POI 时，只调对应的检索子 Agent（`restaurants` / `attractions`）拿候选再局部插入；`change_hotel` 不动 items、交给 `accommodation` 重排；`change_budget` 更新预算上限后交 `budget` 核算。

**Tech Stack:** 后端 Python ≥3.11 · uv · LangGraph（StateGraph + AsyncSqliteSaver/MemorySaver + 条件边/环 + interrupt）· LangChain structured output（Pydantic `function_calling`）· pytest + pytest-asyncio（`asyncio_mode=auto`）。前端 Vue 3 `<script setup>` · Pinia · TypeScript · Vite · bun。

## Global Constraints

- 全程界面文案、提示词与注释用**简体中文**，永不使用日语。
- 后端测试一律对 LLM（各节点模块内的 `build_llm`）与高德 tool（`app.tools.amap`）打桩，不依赖真实 Key/网络；用 `tests/conftest.py` 的 `make_fake_build_llm` / `fake_amap` / `client` fixture。
- 后端命令在 `backend/` 目录执行：测试 `uv run pytest -q`，单文件 `uv run pytest tests/xxx.py -q`。前端命令在 `frontend/` 执行：`bun run build`（`vue-tsc -b && vite build`，类型即契约）。
- **判断一律用规则、不额外调 LLM**：两个按需路由（`route_after_plan` / `route_after_accommodation`）与 refine 的 op 解析，全部读 state 里 `last_intent` + `refine_request` 做确定性路由。LLM 只用于 ①`dispatch_agent` 判意图（规则不确定时兜底）②`dispatch_agent` 对 plan_new 标准化需求 ③`clarify` 评估缺口 ④`itinerary`/`accommodation` 编排 ⑤`summarize`/`answer` 生成。**refine 的 op 解析与补检索关键词全部走规则**。
- **refine 绝不回到全量 `itinerary` 节点**：局部重排逻辑全部在 `refine` 节点内对旧 `day_plans` 增量改，只动 `target_day`。这保证 `test_multiturn_refine` 的 `changed_days=[2]`、第一天原样不变。
- **op → 路由与标志映射表**（确定性，`dispatch_agent` 写 `refine_request`，路由函数据此决策）：

  | op | 含义 | needs_search | needs_budget_recheck | route_after_plan | changed_days |
  |---|---|---|---|---|---|
  | （plan_new，非 op） | 全新规划 | — | — | `accommodation` | itinerary 给的全部天 |
  | `relax` / `remove` | 某天减项/删项 | False | True | `budget` | `[target_day]` |
  | `reorder` | 某天调序 | False | False | `summarize` | `[target_day]` |
  | `tighten` | 某天加项/压缩 | False | True | `budget` | `[target_day]` |
  | `change_meal` | 换餐厅 | True | True | `budget` | `[target_day]` |
  | `add` / `replace` | 加/换景点 | True | True | `budget` | `[target_day]` |
  | `change_budget` | 改预算上限 | False | True | `budget` | `[]`（行程未变，待 budget 核算） |
  | `change_hotel` | 换酒店 | False | True | `accommodation` | `[]`（items 不变，accommodation 重排 hotel） |

- `route_after_plan(state)`：`last_intent=="plan_new"` → `"accommodation"`；否则看 `refine_request.op`：`change_hotel` → `"accommodation"`；`needs_budget_recheck` 为真 → `"budget"`；否则 → `"summarize"`。
- `route_after_accommodation(state)`：`last_intent=="plan_new"` → `"budget"`；否则 `refine_request.get("needs_budget_recheck")` ? `"budget"` : `"summarize"`。
- `route_after_budget(state)`：仅 **plan_new** 超支才回退重排——`last_intent=="plan_new" and budget_check.retry` → `"itinerary"`；否则 → `"summarize"`（refine 超支不回全量 itinerary，避免破坏局部性，超支信息随 `budget_check.note` 透出）。
- SSE 契约不变：`final` 仍发 `{answer, day_plans, budget, plan_version}`，`changed_days` 非空时先发 `plan_patch`。`clarify` interrupt/resume 机制不变。
- 设计文档：[docs/superpowers/specs/2026-06-19-m5-true-multiturn-conversations-design.md](../specs/2026-06-19-m5-true-multiturn-conversations-design.md)（Task 8 同步更新 §3.4/§3.7）。

---

### Task 1: 新建 `dispatch_agent` 节点（合并判意图 + plan_new 标准化 + refine 规则解析）

**Files:**
- Create: `backend/app/graph/nodes/dispatch_agent.py`
- Test: `backend/tests/test_dispatch_agent.py`
- （Task 2 才删 `intent.py`/`dispatch.py` 并改 builder/测试；本任务只新增，不接线）

**Interfaces:**
- Consumes: `app.llm.factory.build_llm`；`app.graph.nodes.dispatch.NormalizedReq`（plan_new 标准化沿用现有模型）；`app.graph.nodes.refine.RefineRequest`（refine 解析沿用现有模型）。
- Produces（后续任务依赖的确切名字与类型）：
  - `class IntentResult(BaseModel)`：`intent: Literal["plan_new","refine_existing","qa"]`、`confidence: float=1.0`、`reason: str=""`、`target_day: int|None=None`、`needs_full_replan: bool=False`（从旧 `intent.py` 平移）。
  - `def route_after_dispatch(state: dict) -> str`：返回 `"plan_new"` / `"refine"` / `"qa"`。
  - `def reset_for_plan_new(state: dict) -> dict`：从旧 `intent.py` 平移。
  - `def _refine_flags(op: str) -> dict`：返回 `{"needs_search": bool, "needs_budget_recheck": bool}`。
  - `def _parse_refine(query: str, target_day: int|None) -> dict`：纯规则，返回完整 `refine_request` dict（`op`/`target_day`/`target_item_name`/`constraints`/`needs_search`/`needs_budget_recheck`）。
  - `async def dispatch_agent(state: dict, config) -> dict`：plan_new 写 `last_intent`+顶层字段+`normalized_req`；refine 写 `last_intent`+`refine_request`；qa 写 `last_intent`。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_dispatch_agent.py`：

```python
import pytest

from app.graph.nodes.dispatch_agent import (
    dispatch_agent, route_after_dispatch, reset_for_plan_new,
    _parse_refine, _refine_flags, IntentResult,
)
from app.graph.nodes.dispatch import NormalizedReq
from tests.conftest import make_fake_build_llm


def test_refine_flags_by_op():
    assert _refine_flags("reorder") == {"needs_search": False, "needs_budget_recheck": False}
    assert _refine_flags("change_meal") == {"needs_search": True, "needs_budget_recheck": True}
    assert _refine_flags("relax") == {"needs_search": False, "needs_budget_recheck": True}
    assert _refine_flags("change_hotel") == {"needs_search": False, "needs_budget_recheck": True}


def test_parse_refine_extracts_op_day_and_flags():
    r = _parse_refine("第二天太赶了，少安排一个景点", target_day=2)
    assert r["op"] == "relax" and r["target_day"] == 2
    assert r["needs_search"] is False and r["needs_budget_recheck"] is True

    r2 = _parse_refine("把第一天晚餐换成火锅", target_day=1)
    assert r2["op"] == "change_meal" and r2["needs_search"] is True
    assert r2["constraints"].get("keywords") == "火锅"

    r3 = _parse_refine("预算改成3000", target_day=None)
    assert r3["op"] == "change_budget" and r3["constraints"].get("budget") == 3000.0
    assert r3["needs_search"] is False


def test_route_after_dispatch_maps_intent():
    assert route_after_dispatch({"last_intent": "plan_new"}) == "plan_new"
    assert route_after_dispatch({"last_intent": "refine_existing"}) == "refine"
    assert route_after_dispatch({"last_intent": "qa"}) == "qa"
    assert route_after_dispatch({}) == "plan_new"


def test_reset_for_plan_new_clears_dirty_state():
    out = reset_for_plan_new({"clarified": True, "retry_count": 2, "day_plans": [{"day": 1}]})
    assert out["clarified"] is False and out["retry_count"] == 0
    assert out["day_plans"] == [] and out["changed_days"] == []


@pytest.mark.asyncio
async def test_first_turn_is_plan_new_and_normalizes(monkeypatch):
    # 无 day_plans → 规则直接判 plan_new（不调 IntentResult LLM）；只调 NormalizedReq
    monkeypatch.setattr("app.graph.nodes.dispatch_agent.build_llm",
                        make_fake_build_llm(structured=NormalizedReq(city="成都", days=2, num_people=2, budget=4000)))
    out = await dispatch_agent({"query": "成都2天2人预算4000"}, None)
    assert out["last_intent"] == "plan_new"
    assert out["city"] == "成都" and out["days"] == 2
    assert out["normalized_req"]["city"] == "成都"


@pytest.mark.asyncio
async def test_refine_turn_parses_by_rule_without_llm(monkeypatch):
    # 已有 day_plans + “第二天少一个” → 规则判 refine_existing 且规则解析 op，不调任何 LLM
    def _boom(*_a, **_k):
        raise AssertionError("refine 解析不应调用 LLM")
    monkeypatch.setattr("app.graph.nodes.dispatch_agent.build_llm", _boom)
    out = await dispatch_agent(
        {"query": "第二天太赶了，少安排一个景点", "day_plans": [{"day": 1}, {"day": 2}]}, None)
    assert out["last_intent"] == "refine_existing"
    assert out["refine_request"]["op"] == "relax"
    assert out["refine_request"]["target_day"] == 2
    assert out["refine_request"]["needs_budget_recheck"] is True


@pytest.mark.asyncio
async def test_qa_turn_only_sets_intent(monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("qa 不应调用 LLM")
    monkeypatch.setattr("app.graph.nodes.dispatch_agent.build_llm", _boom)
    out = await dispatch_agent(
        {"query": "刚才那个行程适合带老人吗？", "day_plans": [{"day": 1}]}, None)
    assert out["last_intent"] == "qa"
    assert "normalized_req" not in out and "refine_request" not in out
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && uv run pytest tests/test_dispatch_agent.py -q`
Expected: FAIL（`app.graph.nodes.dispatch_agent` 模块不存在 / 导入错误）。

- [ ] **Step 3: 实现 `dispatch_agent.py`**

新建 `backend/app/graph/nodes/dispatch_agent.py`：

```python
"""dispatch_agent 节点（M5 fix）：单一前置派发 Agent。

合并原 intent（判意图）+ dispatch（plan_new 标准化）。三类意图：
- plan_new：规则/LLM 判定后，用 NormalizedReq 标准化需求并写顶层字段。
- refine_existing：用规则解析出结构化 RefineRequest（op/target_day/constraints/标志），不调 LLM。
- qa：只写 last_intent，交给 answer 节点。
clarify 在本节点之后、仅 plan_new 经过；clarify 自己把澄清答案并回 normalized_req。
"""
import re
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.graph.nodes.dispatch import NormalizedReq, _SYS as _DISPATCH_SYS

from app.llm.factory import build_llm


class IntentResult(BaseModel):
    intent: Literal["plan_new", "refine_existing", "qa"]
    confidence: float = Field(default=1.0)
    reason: str = Field(default="")
    target_day: int | None = None
    needs_full_replan: bool = False


_INTENT_SYS = (
    "判断用户本轮是在重新规划旅行、修改已有行程，还是只问答。"
    "已有 day_plans 时，提到刚才/第几天/换/删/加/改预算/改酒店/轻松一点通常是 refine_existing；"
    "只询问是否适合、为什么、建议说明是 qa；明确重新规划、换城市、重新做是 plan_new。"
)

_DAY_WORDS = {
    "一": 1, "1": 1, "二": 2, "2": 2, "两": 2, "三": 3, "3": 3,
    "四": 4, "4": 4, "五": 5, "5": 5, "六": 6, "6": 6, "七": 7, "7": 7,
}


def _target_day(text: str) -> int | None:
    for word, day in _DAY_WORDS.items():
        if f"第{word}天" in text or f"day {word}" in text.lower():
            return day
    return None


def _rule_based_intent(query: str, has_plan: bool) -> IntentResult | None:
    if not has_plan:
        return IntentResult(intent="plan_new", confidence=1.0, reason="当前没有可修改的行程")
    text = query.strip()
    if any(k in text for k in ("重新规划", "重新做", "重新安排", "换个城市", "新行程")):
        return IntentResult(intent="plan_new", confidence=0.95, reason="用户明确要求重新规划", needs_full_replan=True)
    day = _target_day(text)
    refine_keywords = ("太赶", "轻松", "少", "删", "删除", "换", "改", "调整", "顺序",
                       "预算", "酒店", "住宿", "晚餐", "午餐", "加")
    if any(k in text for k in refine_keywords):
        return IntentResult(intent="refine_existing", confidence=0.9, reason="用户引用已有行程局部修改", target_day=day)
    if any(k in text for k in ("适合", "吗", "为什么", "怎么", "离", "近吗", "建议")):
        return IntentResult(intent="qa", confidence=0.85, reason="用户询问当前方案")
    return None


def _refine_flags(op: str) -> dict:
    """op → 是否需补检索 / 是否需重算预算。确定性映射（见计划 Global Constraints 表）。"""
    needs_search = op in ("change_meal", "add", "replace")
    needs_budget_recheck = op != "reorder"
    return {"needs_search": needs_search, "needs_budget_recheck": needs_budget_recheck}


def _infer_op(query: str) -> str:
    if "预算" in query:
        return "change_budget"
    if "酒店" in query or "住宿" in query:
        return "change_hotel"
    if any(k in query for k in ("晚餐", "午餐", "餐厅", "吃", "饭")) and "换" in query:
        return "change_meal"
    if any(k in query for k in ("少", "删", "太赶", "轻松")):
        return "relax"
    if "换" in query:
        return "replace"
    if "加" in query:
        return "add"
    return "reorder"


def _parse_refine(query: str, target_day: int | None) -> dict:
    """纯规则把自然语言修改解析成结构化 RefineRequest dict。不调 LLM。"""
    op = _infer_op(query)
    constraints: dict = {}
    # “换成X”/“改成X” 的 X 作为检索关键词或目标项
    m = re.search(r"(?:换成|改成|换个|改为)\s*([一-龥A-Za-z0-9]{1,12})", query)
    if m:
        constraints["keywords"] = m.group(1)
    if op == "change_budget":
        num = re.search(r"(\d{3,6})", query)
        if num:
            constraints["budget"] = float(num.group(1))
    flags = _refine_flags(op)
    return {
        "op": op,
        "target_day": target_day,
        "target_item_name": constraints.get("keywords", "") if op in ("replace", "change_meal") else "",
        "constraints": constraints,
        "needs_search": flags["needs_search"],
        "needs_budget_recheck": flags["needs_budget_recheck"],
    }


async def dispatch_agent(state: dict, config: RunnableConfig) -> dict:
    query = state.get("query", "")
    has_plan = bool(state.get("day_plans"))
    result = _rule_based_intent(query, has_plan)
    if result is None:
        llm = build_llm(temperature=0).with_structured_output(IntentResult, method="function_calling")
        result = await llm.ainvoke([
            SystemMessage(content=_INTENT_SYS),
            HumanMessage(content=str({
                "query": query,
                "conversation_summary": state.get("conversation_summary", ""),
                "normalized_req": state.get("normalized_req", {}) or {},
                "has_day_plans": has_plan,
            })),
        ], config=config)
        if result.confidence < 0.55:
            result.intent = "qa"

    if result.intent == "qa":
        return {"last_intent": "qa", "refine_request": {"reason": result.reason}}

    if result.intent == "refine_existing":
        return {
            "last_intent": "refine_existing",
            "refine_request": _parse_refine(query, result.target_day),
        }

    # plan_new：标准化需求（LLM），写顶层字段供检索消费
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
    data = req.model_dump()
    return {"last_intent": "plan_new", **data, "normalized_req": data}


def route_after_dispatch(state: dict) -> str:
    intent_name = state.get("last_intent") or "plan_new"
    if intent_name == "refine_existing":
        return "refine"
    if intent_name == "qa":
        return "answer"
    return "plan_new"


def reset_for_plan_new(state: dict) -> dict:
    return {
        "clarified": False,
        "clarify_round": 0,
        "retry_count": 0,
        "day_plans": [],
        "budget_check": {},
        "daily_centers": [],
        "changed_days": [],
    }
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd backend && uv run pytest tests/test_dispatch_agent.py -q`
Expected: PASS（8 个用例全绿）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/nodes/dispatch_agent.py backend/tests/test_dispatch_agent.py
git commit -m "feat(m5fix): 新增 dispatch_agent 合并判意图+标准化+refine规则解析" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: clarify 写回需求 + 新增 `retrieve` fan-out 锚点 + builder 前半接线 + 常量与受影响测试迁移

**Files:**
- Modify: `backend/app/graph/nodes/clarify.py`
- Create: `backend/app/graph/nodes/retrieve.py`
- Modify: `backend/app/graph/builder.py`
- Modify: `backend/app/core/constants.py`
- Modify: `backend/tests/test_clarify_interrupt.py`、`backend/tests/test_multiturn_qa.py`、`backend/tests/test_multiturn_refine.py`、`backend/tests/test_chat_stream_m2.py`、`backend/tests/test_chat_stream_m4.py`
- Delete: `backend/app/graph/nodes/intent.py`（其 `NormalizedReq` 无依赖；`IntentResult`/`reset_for_plan_new` 已平移到 `dispatch_agent`）

**Interfaces:**
- Consumes: `dispatch_agent.dispatch_agent`/`route_after_dispatch`/`reset_for_plan_new`（Task 1）；`dispatch.NormalizedReq`（保留，dispatch_agent 仍 import 它）。
- Produces:
  - `def _apply_answer(field: str, answer: str, state: dict) -> dict`：把单条澄清答案并入顶层字段 + `normalized_req`。
  - `async def retrieve(state, config) -> dict`：pass-through，返回 `{}`（fan-out 锚点）。
  - 编译图前半拓扑：`START → memory → dispatch_agent ─{plan_new→reset_plan_new→clarify, refine→refine, qa→answer}`；`clarify ─{clarify, retrieve}`；`retrieve → {weather,attractions,restaurants,transport}`。

> 注意：`intent.py` 删除后，旧测试里 `from app.graph.nodes import ... dispatch as d` 的 `d.build_llm` 打桩点全部迁移到 `dispatch_agent`（plan_new 标准化的 LLM 现在在 dispatch_agent 模块）。`dispatch.py` 文件**保留**（`NormalizedReq` 与 `_SYS` 仍被 dispatch_agent import），但其 `dispatch` 函数不再进图。

- [ ] **Step 1: 写失败测试（clarify 写回 + retrieve + builder 拓扑）**

新建 `backend/tests/test_dispatch_topology.py`：

```python
from app.graph.builder import build_graph
from app.graph.nodes.clarify import _apply_answer


def test_apply_answer_maps_known_fields():
    assert _apply_answer("city", "成都", {})["city"] == "成都"
    out = _apply_answer("days", "3", {})
    assert out["days"] == 3 and out["normalized_req"]["days"] == 3
    out2 = _apply_answer("budget", "4000", {})
    assert out2["budget"] == 4000.0
    # 未知字段并入 preferences
    out3 = _apply_answer("风格", "美食", {"preferences": {}})
    assert out3["preferences"]["风格"] == "美食"


def test_graph_uses_dispatch_agent_not_intent_dispatch():
    nodes = set(build_graph().get_graph().nodes.keys())
    assert "dispatch_agent" in nodes and "retrieve" in nodes
    assert "intent" not in nodes and "dispatch" not in nodes


def test_graph_front_edges():
    gg = build_graph().get_graph()
    edges = {(e.source, e.target) for e in gg.edges}
    assert ("memory", "dispatch_agent") in edges
    assert ("reset_plan_new", "clarify") in edges
    for n in ("weather", "attractions", "restaurants", "transport"):
        assert ("retrieve", n) in edges
        assert (n, "itinerary") in edges
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && uv run pytest tests/test_dispatch_topology.py -q`
Expected: FAIL（`_apply_answer` 不存在 / 图仍含 intent、dispatch，无 dispatch_agent、retrieve）。

- [ ] **Step 3: clarify 加 `_apply_answer` 并在 resume 时写回**

修改 `backend/app/graph/nodes/clarify.py`：

3a. 在 `from app.llm.factory import build_llm` 之后新增字段映射纯函数：

```python
_DIRECT_FIELDS = {"city", "start_date"}
_INT_FIELDS = {"days", "num_people"}
_FLOAT_FIELDS = {"budget"}


def _apply_answer(field: str, answer: str, state: dict) -> dict:
    """把一条澄清答案并入顶层字段 + normalized_req。未知 field 进 preferences。纯函数。"""
    req = dict(state.get("normalized_req", {}) or {})
    patch: dict = {}
    raw = (answer or "").strip()
    if field in _INT_FIELDS:
        m = re.search(r"\d+", raw)
        val = int(m.group()) if m else req.get(field, 0)
    elif field in _FLOAT_FIELDS:
        m = re.search(r"\d+(?:\.\d+)?", raw)
        val = float(m.group()) if m else req.get(field, 0.0)
    elif field in _DIRECT_FIELDS:
        val = raw
    else:
        prefs = dict(req.get("preferences", {}) or {})
        prefs[field] = raw
        req["preferences"] = prefs
        patch["preferences"] = prefs
        return {**patch, "normalized_req": req}
    req[field] = val
    patch[field] = val
    return {**patch, "normalized_req": req}
```

3b. 在文件顶部 import 段加 `import re`（与现有 import 同段）。

3c. 把 `clarify` 函数体改为在 resume 后调用 `_apply_answer`（替换现有 `return` 块）：

把：

```python
    answer = interrupt(payload)  # 暂停；resume 后 answer = Command(resume=...) 的值
    return {
        "clarify_history": [{**payload, "answer": answer}],
        "clarify_round": rnd + 1,
        "clarified": False,
    }
```

替换为：

```python
    answer = interrupt(payload)  # 暂停；resume 后 answer = Command(resume=...) 的值
    return {
        **_apply_answer(g.field, answer, state),
        "clarify_history": [{**payload, "answer": answer}],
        "clarify_round": rnd + 1,
        "clarified": False,
    }
```

3d. 把 `route_after_clarify` 的放行目标从 `dispatch` 改为 `retrieve`：

```python
def route_after_clarify(state) -> str:
    return "retrieve" if state.get("clarified") else "clarify"
```

- [ ] **Step 4: 新建 `retrieve` 锚点节点**

新建 `backend/app/graph/nodes/retrieve.py`：

```python
"""retrieve 节点（M5 fix）：clarify 放行后的并行检索 fan-out 锚点。

本身不做事（pass-through），仅作为「clarify → 4 个检索子 Agent 并行」的单一上游，
让 LangGraph 从这里 fan-out 到 weather/attractions/restaurants/transport。
"""


async def retrieve(state, config) -> dict:
    return {}
```

- [ ] **Step 5: 重写 builder 前半拓扑**

修改 `backend/app/graph/builder.py`：

5a. 替换 import 段顶部（删 intent/dispatch 节点函数，加 dispatch_agent/retrieve）。把：

```python
from app.graph.nodes.memory import memory
from app.graph.nodes.intent import intent, reset_for_plan_new, route_after_intent
from app.graph.nodes.clarify import clarify, route_after_clarify
from app.graph.nodes.dispatch import dispatch
```

替换为：

```python
from app.graph.nodes.memory import memory
from app.graph.nodes.dispatch_agent import dispatch_agent, reset_for_plan_new, route_after_dispatch
from app.graph.nodes.clarify import clarify, route_after_clarify
from app.graph.nodes.retrieve import retrieve
```

5b. 把节点注册列表与前半边替换。将现有 `build_graph` 里：

```python
    for name, fn in [
        ("memory", memory), ("intent", intent), ("reset_plan_new", reset_plan_new),
        ("clarify", clarify), ("dispatch", dispatch),
        ("weather", weather), ("attractions", attractions),
        ("restaurants", restaurants), ("transport", transport),
        ("itinerary", itinerary), ("accommodation", accommodation),
        ("budget", budget), ("summarize", summarize),
        ("refine", refine), ("answer", answer), ("memory_update", memory_update),
    ]:
        g.add_node(name, fn)

    g.add_edge(START, "memory")
    g.add_edge("memory", "intent")
    g.add_conditional_edges("intent", route_after_intent,
                            {"plan_new": "reset_plan_new", "refine": "refine", "answer": "answer"})
    g.add_edge("reset_plan_new", "clarify")
    g.add_conditional_edges("clarify", route_after_clarify,
                            {"clarify": "clarify", "dispatch": "dispatch"})
    for n in ("weather", "attractions", "restaurants", "transport"):
        g.add_edge("dispatch", n)
        g.add_edge(n, "itinerary")
```

替换为：

```python
    for name, fn in [
        ("memory", memory), ("dispatch_agent", dispatch_agent), ("reset_plan_new", reset_plan_new),
        ("clarify", clarify), ("retrieve", retrieve),
        ("weather", weather), ("attractions", attractions),
        ("restaurants", restaurants), ("transport", transport),
        ("itinerary", itinerary), ("accommodation", accommodation),
        ("budget", budget), ("summarize", summarize),
        ("refine", refine), ("answer", answer), ("memory_update", memory_update),
    ]:
        g.add_node(name, fn)

    g.add_edge(START, "memory")
    g.add_edge("memory", "dispatch_agent")
    g.add_conditional_edges("dispatch_agent", route_after_dispatch,
                            {"plan_new": "reset_plan_new", "refine": "refine", "answer": "answer"})
    g.add_edge("reset_plan_new", "clarify")
    g.add_conditional_edges("clarify", route_after_clarify,
                            {"clarify": "clarify", "retrieve": "retrieve"})
    for n in ("weather", "attractions", "restaurants", "transport"):
        g.add_edge("retrieve", n)
        g.add_edge(n, "itinerary")
```

> 本任务后半边（itinerary/accommodation/budget/refine）暂保持现状不动，Task 3 再改。删 `reset_plan_new` 旧 wrapper：把文件顶部 `def reset_plan_new(state): return reset_for_plan_new(state)` 保留即可（仍引用，已从 dispatch_agent 导入 `reset_for_plan_new`）。

- [ ] **Step 6: 更新常量 NODES / NODE_LABELS**

修改 `backend/app/core/constants.py`：

6a. 把 `NODES` 改为（去 `intent`/`dispatch`，加 `dispatch_agent`/`retrieve`）：

```python
NODES = {"memory", "dispatch_agent", "clarify", "retrieve", "weather", "attractions",
         "restaurants", "transport", "itinerary", "refine", "answer",
         "accommodation", "budget", "summarize", "memory_update"}
```

6b. 把 `NODE_LABELS` 里 `"intent"` 与 `"dispatch"` 两行替换为：

```python
    "dispatch_agent": "正在判断任务并分发…",
    "retrieve": "正在并行检索…",
```

- [ ] **Step 7: 迁移受影响测试的打桩点（intent/dispatch → dispatch_agent）**

7a. `backend/tests/test_chat_stream_m2.py`：把 `_stub_nodes` 里：

```python
    from app.graph.nodes import clarify as c, dispatch as d, itinerary as it, summarize as s
    from app.graph.nodes.dispatch import NormalizedReq
    ...
    monkeypatch.setattr(d, "build_llm", make_fake_build_llm(
        structured=NormalizedReq(city="成都", days=1, num_people=2,
                                 preferences={"food": "辣"}, budget=2000.0)))
```

改为：

```python
    from app.graph.nodes import clarify as c, dispatch_agent as d, itinerary as it, summarize as s
    from app.graph.nodes.dispatch import NormalizedReq
    ...
    monkeypatch.setattr(d, "build_llm", make_fake_build_llm(
        structured=NormalizedReq(city="成都", days=1, num_people=2,
                                 preferences={"food": "辣"}, budget=2000.0)))
```

7b. `backend/tests/test_chat_stream_m4.py`、`backend/tests/test_multiturn_qa.py`、`backend/tests/test_multiturn_refine.py`：同样把 `dispatch as d` 改为 `dispatch_agent as d`（`d.build_llm` 打桩点不变，`NormalizedReq` 仍从 `app.graph.nodes.dispatch` 导入）。

7c. `backend/tests/test_clarify_interrupt.py`：
- 把 `from app.graph.nodes import clarify as c, dispatch as d, ...` 改为 `clarify as c, dispatch_agent as d, ...`。
- 把末尾断言 `assert '"node": "intent"' not in second` 改为 `assert '"node": "dispatch_agent"' not in second`（resume 从 clarify 暂停点恢复，仍应跳过 memory/dispatch_agent）。

- [ ] **Step 8: 删除 intent.py 并跑全量**

```bash
cd backend && rm app/graph/nodes/intent.py
uv run pytest tests/test_dispatch_topology.py tests/test_dispatch_agent.py -q
```
Expected: 两文件全绿。

- [ ] **Step 9: 跑全量后端测试，确认前半重构无回归**

Run: `cd backend && uv run pytest -q`
Expected: 全绿。重点：`test_chat_stream_m2`（plan_new 全流程，dispatch_agent→clarify→retrieve→检索→itinerary）、`test_clarify_interrupt`（resume 跳过 dispatch_agent）、`test_multiturn_qa`（qa 直达 answer）、`test_multiturn_refine`（refine 仍 → budget，本任务未改后半，仍走旧 `refine→budget` 边）。

- [ ] **Step 10: Commit**

```bash
git add backend/app/graph/nodes/clarify.py backend/app/graph/nodes/retrieve.py backend/app/graph/builder.py backend/app/core/constants.py backend/tests/
git rm backend/app/graph/nodes/intent.py
git commit -m "feat(m5fix): 物理合并 intent+dispatch 为 dispatch_agent，clarify 写回需求 + retrieve 锚点" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: 两个按需路由 + builder 后半接线（酒店需重排? / 预算需重算?）

**Files:**
- Create: `backend/app/graph/nodes/routing.py`（两个规则路由 + budget 路由增强）
- Modify: `backend/app/graph/builder.py`
- Modify: `backend/app/graph/nodes/budget.py`（`route_after_budget` 改为只 plan_new 回退）
- Test: `backend/tests/test_need_routing.py`

**Interfaces:**
- Consumes: `state` 的 `last_intent`、`refine_request`、`budget_check`。
- Produces:
  - `def route_after_plan(state: dict) -> str`：`"accommodation"|"budget"|"summarize"`。
  - `def route_after_accommodation(state: dict) -> str`：`"budget"|"summarize"`。
  - `route_after_budget(state)` 语义改为：仅 `last_intent=="plan_new" and budget_check.retry` → `"itinerary"`，否则 `"summarize"`。
  - 后半拓扑：`itinerary`/`refine` 各 `add_conditional_edges(route_after_plan, {accommodation, budget, summarize})`；`accommodation add_conditional_edges(route_after_accommodation, {budget, summarize})`；`budget add_conditional_edges(route_after_budget, {itinerary, summarize})`。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_need_routing.py`：

```python
from app.graph.nodes.routing import route_after_plan, route_after_accommodation
from app.graph.nodes.budget import route_after_budget


def test_plan_new_always_full_chain():
    s = {"last_intent": "plan_new"}
    assert route_after_plan(s) == "accommodation"
    assert route_after_accommodation(s) == "budget"


def test_refine_change_hotel_goes_accommodation():
    s = {"last_intent": "refine_existing",
         "refine_request": {"op": "change_hotel", "needs_budget_recheck": True}}
    assert route_after_plan(s) == "accommodation"
    assert route_after_accommodation(s) == "budget"   # 换酒店改价 → 仍重算预算


def test_refine_cost_change_skips_hotel_but_rechecks_budget():
    s = {"last_intent": "refine_existing",
         "refine_request": {"op": "relax", "needs_budget_recheck": True}}
    assert route_after_plan(s) == "budget"


def test_refine_reorder_skips_both():
    s = {"last_intent": "refine_existing",
         "refine_request": {"op": "reorder", "needs_budget_recheck": False}}
    assert route_after_plan(s) == "summarize"


def test_budget_retry_only_for_plan_new():
    assert route_after_budget({"last_intent": "plan_new", "budget_check": {"retry": True}}) == "itinerary"
    # refine 超支不回全量 itinerary
    assert route_after_budget({"last_intent": "refine_existing", "budget_check": {"retry": True}}) == "summarize"
    assert route_after_budget({"last_intent": "plan_new", "budget_check": {"retry": False}}) == "summarize"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && uv run pytest tests/test_need_routing.py -q`
Expected: FAIL（`app.graph.nodes.routing` 不存在；`route_after_budget` 旧实现不读 `last_intent`，`test_budget_retry_only_for_plan_new` 第二条失败）。

- [ ] **Step 3: 新建 `routing.py`**

新建 `backend/app/graph/nodes/routing.py`：

```python
"""M5 fix 按需重排路由（规则，不调 LLM）。

对应架构图两个判断菱形：
- route_after_plan：itinerary(plan_new) / refine 出口 → 是否重排酒店 / 是否重算预算 / 都不需。
- route_after_accommodation：分配完酒店后 → 是否重算预算。
依据 state 里的 last_intent + refine_request（dispatch_agent/refine 已写）。
"""


def route_after_plan(state: dict) -> str:
    if (state.get("last_intent") or "plan_new") == "plan_new":
        return "accommodation"
    req = state.get("refine_request", {}) or {}
    if req.get("op") == "change_hotel":
        return "accommodation"
    if req.get("needs_budget_recheck"):
        return "budget"
    return "summarize"


def route_after_accommodation(state: dict) -> str:
    if (state.get("last_intent") or "plan_new") == "plan_new":
        return "budget"
    return "budget" if (state.get("refine_request", {}) or {}).get("needs_budget_recheck") else "summarize"
```

- [ ] **Step 4: budget 路由增强（只 plan_new 回退）**

修改 `backend/app/graph/nodes/budget.py`，把：

```python
def route_after_budget(state: TripState) -> str:
    return "itinerary" if state.get("budget_check", {}).get("retry") else "summarize"
```

替换为：

```python
def route_after_budget(state: TripState) -> str:
    # 仅 plan_new 超支才回全量 itinerary 重排；refine 超支不回退（避免破坏局部修改），
    # 超支信息随 budget_check.note 透出。
    plan_new = (state.get("last_intent") or "plan_new") == "plan_new"
    retry = bool(state.get("budget_check", {}).get("retry"))
    return "itinerary" if (plan_new and retry) else "summarize"
```

- [ ] **Step 5: builder 后半接线**

修改 `backend/app/graph/builder.py`：

5a. import 段加入路由：

```python
from app.graph.nodes.routing import route_after_plan, route_after_accommodation
```

5b. 把现有后半边：

```python
    g.add_edge("itinerary", "accommodation")
    g.add_edge("accommodation", "budget")
    g.add_conditional_edges("budget", route_after_budget,
                            {"itinerary": "itinerary", "summarize": "summarize"})
    g.add_edge("refine", "budget")
```

替换为：

```python
    g.add_conditional_edges("itinerary", route_after_plan,
                            {"accommodation": "accommodation", "budget": "budget", "summarize": "summarize"})
    g.add_conditional_edges("refine", route_after_plan,
                            {"accommodation": "accommodation", "budget": "budget", "summarize": "summarize"})
    g.add_conditional_edges("accommodation", route_after_accommodation,
                            {"budget": "budget", "summarize": "summarize"})
    g.add_conditional_edges("budget", route_after_budget,
                            {"itinerary": "itinerary", "summarize": "summarize"})
```

- [ ] **Step 6: 运行测试，确认通过**

Run: `cd backend && uv run pytest tests/test_need_routing.py -q`
Expected: PASS（5 个用例全绿）。

- [ ] **Step 7: 更新 test_builder.py 后半断言**

把 `backend/tests/test_builder.py` 的 `test_graph_has_m4_accommodation_and_budget_edges` 整体替换为：

```python
def test_graph_has_m5fix_conditional_chain():
    g = build_graph()
    gg = g.get_graph()
    nodes = set(gg.nodes.keys())
    assert "accommodation" in nodes and "budget" in nodes
    edges = {(e.source, e.target) for e in gg.edges}
    # itinerary 与 refine 都条件分流到 accommodation/budget/summarize
    for src in ("itinerary", "refine"):
        assert {(src, "accommodation"), (src, "budget"), (src, "summarize")} <= edges
    # accommodation 条件分流到 budget/summarize
    assert {("accommodation", "budget"), ("accommodation", "summarize")} <= edges
    # budget 超支回退仍可达 itinerary
    assert ("budget", "itinerary") in edges
```

并把 `test_graph_has_all_core_nodes` 里的 `"dispatch"` 改为 `"dispatch_agent"`、加 `"retrieve"`。

- [ ] **Step 8: 全量后端测试**

Run: `cd backend && uv run pytest -q`
Expected: 全绿。重点 `test_multiturn_refine`：现在 refine（op=relax, needs_budget_recheck=True）→ `route_after_plan` → `"budget"` → `route_after_budget`（refine 不回退）→ `summarize`，`changed_days=[2]` 仍由 refine 节点保证。`test_chat_stream_m4`（plan_new 超支回退）仍走 itinerary→accommodation→budget→itinerary 回退。

- [ ] **Step 9: Commit**

```bash
git add backend/app/graph/nodes/routing.py backend/app/graph/nodes/budget.py backend/app/graph/builder.py backend/tests/test_need_routing.py backend/tests/test_builder.py
git commit -m "feat(m5fix): 按需重排路由 route_after_plan/accommodation + budget 仅plan_new回退" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: refine 改 async + 本地确定性操作（reorder / change_budget / change_hotel / relax）

**Files:**
- Modify: `backend/app/graph/nodes/refine.py`（整体重写为 async 分发）
- Test: `backend/tests/test_refine_node.py`

**Interfaces:**
- Consumes: `state` 的 `query`、`day_plans`、`refine_request`（Task 1 由 dispatch_agent 写：`op`/`target_day`/`constraints`/`needs_search`/`needs_budget_recheck`）、`plan_version`；`app.tools.amap`（Task 5 才用）。
- Produces（后续依赖）：
  - `class RefineRequest(BaseModel)`：保留（结构化承载/文档用，字段同现状）。
  - `def _find_day(day_plans: list, target_day: int|None) -> int|None`：返回匹配天的下标。
  - `def _relax_day(day_plan: dict) -> dict`：删最后一个可删项（保留现状）。
  - `def _reorder_day(day_plan: dict) -> dict`：把 items 倒序（确定性局部调序）。
  - `async def refine(state, config=None) -> dict`：按 op 局部改 `day_plans`，输出 `day_plans`/`refine_request`/`changed_days`/`plan_version`，change_budget 额外输出 `budget`。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_refine_node.py`：

```python
import pytest

from app.graph.nodes.refine import refine, _find_day, _reorder_day


def _plan():
    return [
        {"day": 1, "items": [
            {"type": "attraction", "name": "武侯祠", "poi_id": "B1"},
            {"type": "meal", "name": "陈麻婆", "poi_id": "M1"}]},
        {"day": 2, "items": [
            {"type": "attraction", "name": "杜甫草堂", "poi_id": "B2"},
            {"type": "attraction", "name": "金沙遗址", "poi_id": "B3"}]},
    ]


def test_find_day():
    assert _find_day(_plan(), 2) == 1
    assert _find_day(_plan(), 9) is None
    assert _find_day(_plan(), None) is None


def test_reorder_day_reverses_items():
    out = _reorder_day({"day": 1, "items": [{"name": "A"}, {"name": "B"}]})
    assert [i["name"] for i in out["items"]] == ["B", "A"]


@pytest.mark.asyncio
async def test_relax_only_target_day():
    state = {"query": "第二天太赶了，少一个景点", "day_plans": _plan(), "plan_version": 1,
             "refine_request": {"op": "relax", "target_day": 2, "needs_budget_recheck": True}}
    out = await refine(state)
    assert out["changed_days"] == [2]
    assert [i["name"] for i in out["day_plans"][0]["items"]] == ["武侯祠", "陈麻婆"]  # 第一天不动
    assert len(out["day_plans"][1]["items"]) == 1
    assert out["plan_version"] == 2


@pytest.mark.asyncio
async def test_reorder_changes_only_order():
    state = {"query": "第一天顺序调一下", "day_plans": _plan(), "plan_version": 1,
             "refine_request": {"op": "reorder", "target_day": 1, "needs_budget_recheck": False}}
    out = await refine(state)
    assert out["changed_days"] == [1]
    assert [i["name"] for i in out["day_plans"][0]["items"]] == ["陈麻婆", "武侯祠"]


@pytest.mark.asyncio
async def test_change_budget_updates_limit_without_touching_plan():
    state = {"query": "预算改成3000", "day_plans": _plan(), "plan_version": 1, "budget": 5000,
             "refine_request": {"op": "change_budget", "target_day": None,
                                "constraints": {"budget": 3000.0}, "needs_budget_recheck": True}}
    out = await refine(state)
    assert out["budget"] == 3000.0
    assert out["changed_days"] == []
    assert out["day_plans"] == _plan()       # 行程不动
    assert out["plan_version"] == 1           # 行程未变，版本不增


@pytest.mark.asyncio
async def test_change_hotel_marks_overnight_days_for_refresh():
    state = {"query": "换个离地铁近的酒店", "day_plans": _plan(), "plan_version": 1,
             "refine_request": {"op": "change_hotel", "target_day": None, "needs_budget_recheck": True}}
    out = await refine(state)
    # items 不动；标记过夜日（第一天）待 accommodation 重排 + 前端刷新
    assert out["changed_days"] == [1]
    assert out["day_plans"][0]["items"] == _plan()[0]["items"]
    assert out["plan_version"] == 2
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && uv run pytest tests/test_refine_node.py -q`
Expected: FAIL（`_reorder_day` 不存在；`refine` 仍是 sync 且不处理 reorder/change_budget/change_hotel）。

- [ ] **Step 3: 整体重写 `refine.py`**

整体替换 `backend/app/graph/nodes/refine.py`：

```python
"""M5 fix refine：async 局部重排，只改 target_day，绝不回全量 itinerary。

op 由 dispatch_agent 用规则解析进 state['refine_request']。本节点按 op 在旧 day_plans 上增量改：
- relax/remove/tighten：删/压缩 target_day 的项。
- reorder：target_day 内 items 倒序（确定性局部调序）。
- change_budget：更新预算上限（day_plans 不变，交 budget 核算）。
- change_hotel：items 不动，标记过夜日交 accommodation 重排。
- change_meal/add/replace：补检索后局部插入/替换（见 Task 5）。
"""
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, Field

from app.tools import amap


class RefineRequest(BaseModel):
    op: Literal["add", "remove", "replace", "relax", "tighten", "change_budget", "change_hotel", "change_meal", "reorder"]
    target_day: int | None = None
    target_item_name: str | None = None
    constraints: dict = Field(default_factory=dict)
    needs_search: bool = False
    needs_budget_recheck: bool = True


def _infer_op(query: str) -> str:
    if "预算" in query:
        return "change_budget"
    if "酒店" in query or "住宿" in query:
        return "change_hotel"
    if any(k in query for k in ("晚餐", "午餐", "餐厅", "吃", "饭")) and "换" in query:
        return "change_meal"
    if any(k in query for k in ("少", "删", "太赶", "轻松")):
        return "relax"
    if "换" in query:
        return "replace"
    if "加" in query:
        return "add"
    return "reorder"


def _find_day(day_plans: list, target_day: int | None) -> int | None:
    if target_day is None:
        return None
    for idx, day in enumerate(day_plans):
        if day.get("day") == target_day:
            return idx
    return None


def _relax_day(day_plan: dict) -> dict:
    updated = dict(day_plan)
    items = list(updated.get("items", []) or [])
    removable = [i for i, it in enumerate(items)
                 if it.get("type") in ("attraction", "meal") and it.get("name")]
    if removable:
        items.pop(removable[-1])
    updated["items"] = items
    return updated


def _reorder_day(day_plan: dict) -> dict:
    updated = dict(day_plan)
    updated["items"] = list(reversed(updated.get("items", []) or []))
    return updated


def _poi_to_item(poi: dict, type_: str) -> dict:
    """高德 POI → PlanItem dict（与 itinerary.PlanItem 字段对齐）。"""
    return {
        "type": type_,
        "name": poi.get("name", ""),
        "poi_id": poi.get("poi_id", ""),
        "location": {"lng": poi.get("lng", 0.0), "lat": poi.get("lat", 0.0)},
        "start": "", "end": "", "indoor": False, "note": "", "cost": 0.0,
    }


def _set_meal(day_plan: dict, new_item: dict) -> dict:
    """替换当天第一个 meal 项；没有则追加。"""
    updated = dict(day_plan)
    items = list(updated.get("items", []) or [])
    for i, it in enumerate(items):
        if it.get("type") == "meal":
            items[i] = new_item
            break
    else:
        items.append(new_item)
    updated["items"] = items
    return updated


def _add_or_replace_attraction(day_plan: dict, new_item: dict, replace: bool) -> dict:
    updated = dict(day_plan)
    items = list(updated.get("items", []) or [])
    if replace:
        for i, it in enumerate(items):
            if it.get("type") == "attraction":
                items[i] = new_item
                break
        else:
            items.append(new_item)
    else:
        items.append(new_item)
    updated["items"] = items
    return updated


def _overnight_days(day_plans: list) -> list:
    days = sorted(d.get("day", 0) for d in day_plans)
    return days[:-1] if len(days) > 1 else days


async def refine(state, config=None) -> dict:
    query = state.get("query", "")
    day_plans = deepcopy(state.get("day_plans", []) or [])
    request = dict(state.get("refine_request", {}) or {})
    op = request.get("op") or _infer_op(query)
    target_day = request.get("target_day")
    constraints = request.get("constraints", {}) or {}
    idx = _find_day(day_plans, target_day)
    changed_days: list[int] = []
    extra: dict = {}

    if op in ("relax", "remove", "tighten") and idx is not None:
        day_plans[idx] = _relax_day(day_plans[idx])
        changed_days = [target_day]
    elif op == "reorder" and idx is not None:
        day_plans[idx] = _reorder_day(day_plans[idx])
        changed_days = [target_day]
    elif op == "change_budget":
        new_budget = constraints.get("budget")
        if new_budget:
            extra["budget"] = float(new_budget)
    elif op == "change_hotel":
        changed_days = _overnight_days(day_plans)  # items 不动，accommodation 重排 hotel
    elif op in ("change_meal", "replace", "add") and idx is not None:
        changed_days = await _apply_search_op(state, day_plans, idx, op, constraints)

    plan_version = (state.get("plan_version", 0) or 0) + (1 if changed_days else 0)
    return {
        **extra,
        "day_plans": day_plans,
        "refine_request": {**request, "op": op, "target_day": target_day},
        "changed_days": changed_days,
        "plan_version": plan_version,
    }


async def _apply_search_op(state, day_plans, idx, op, constraints) -> list:
    """Task 5 实现：补检索后局部插入/替换。Task 4 先占位（不改 items）。"""
    return []
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd backend && uv run pytest tests/test_refine_node.py -q`
Expected: PASS（reorder/relax/change_budget/change_hotel 用例全绿；change_meal/add/replace 因 `_apply_search_op` 占位返回 `[]`，本任务不测）。

- [ ] **Step 5: 全量后端测试（确认 refine 改 async 不破端到端）**

Run: `cd backend && uv run pytest -q`
Expected: 全绿。`test_multiturn_refine`（op=relax）→ refine 局部删第二天 → `route_after_plan`→budget→`route_after_budget`(refine)→summarize，`changed_days=[2]`、第一天原样。

- [ ] **Step 6: Commit**

```bash
git add backend/app/graph/nodes/refine.py backend/tests/test_refine_node.py
git commit -m "feat(m5fix): refine 改 async + reorder/change_budget/change_hotel 本地操作" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: refine 选择性补检索（change_meal → restaurants，add/replace → attractions）

**Files:**
- Modify: `backend/app/graph/nodes/refine.py`（实现 `_apply_search_op`）
- Test: `backend/tests/test_refine_search.py`

**Interfaces:**
- Consumes: `state` 的 `city`；`refine_request.constraints.keywords`；`app.tools.amap.search_poi(city, keywords, poi_type)`；Task 4 的 `_poi_to_item`/`_set_meal`/`_add_or_replace_attraction`。
- Produces: `_apply_search_op(state, day_plans, idx, op, constraints) -> list[int]`：补检索成功则就地改 `day_plans[idx]` 并返回 `[target_day]`，失败/空降级返回 `[]`。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_refine_search.py`：

```python
import pytest

from app.graph.nodes.refine import refine


def _plan():
    return [
        {"day": 1, "items": [
            {"type": "attraction", "name": "武侯祠", "poi_id": "B1"},
            {"type": "meal", "name": "陈麻婆", "poi_id": "M1"}]},
        {"day": 2, "items": [
            {"type": "attraction", "name": "杜甫草堂", "poi_id": "B2"}]},
    ]


@pytest.mark.asyncio
async def test_change_meal_swaps_target_day_meal(fake_amap, monkeypatch):
    fake_amap["search_poi"] = [{"name": "蜀大侠火锅", "poi_id": "M9", "lng": 104.0, "lat": 30.6}]
    state = {"query": "把第一天晚餐换成火锅", "city": "成都", "day_plans": _plan(), "plan_version": 1,
             "refine_request": {"op": "change_meal", "target_day": 1, "needs_search": True,
                                "constraints": {"keywords": "火锅"}, "needs_budget_recheck": True}}
    out = await refine(state)
    assert out["changed_days"] == [1]
    meals = [i["name"] for i in out["day_plans"][0]["items"] if i["type"] == "meal"]
    assert meals == ["蜀大侠火锅"]
    assert out["day_plans"][1]["items"] == _plan()[1]["items"]   # 第二天不动


@pytest.mark.asyncio
async def test_add_attraction_appends_to_target_day(fake_amap, monkeypatch):
    fake_amap["search_poi"] = [{"name": "宽窄巷子", "poi_id": "B9", "lng": 104.0, "lat": 30.6}]
    state = {"query": "第二天加一个景点", "city": "成都", "day_plans": _plan(), "plan_version": 1,
             "refine_request": {"op": "add", "target_day": 2, "needs_search": True,
                                "constraints": {}, "needs_budget_recheck": True}}
    out = await refine(state)
    assert out["changed_days"] == [2]
    assert [i["name"] for i in out["day_plans"][1]["items"]] == ["杜甫草堂", "宽窄巷子"]


@pytest.mark.asyncio
async def test_search_empty_degrades_to_no_change(fake_amap, monkeypatch):
    fake_amap["search_poi"] = []   # 检索空 → 不改，changed_days 空
    state = {"query": "第一天晚餐换成日料", "city": "成都", "day_plans": _plan(), "plan_version": 1,
             "refine_request": {"op": "change_meal", "target_day": 1, "needs_search": True,
                                "constraints": {"keywords": "日料"}, "needs_budget_recheck": True}}
    out = await refine(state)
    assert out["changed_days"] == []
    assert out["day_plans"] == _plan()
    assert out["plan_version"] == 1
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && uv run pytest tests/test_refine_search.py -q`
Expected: FAIL（`_apply_search_op` 占位返回 `[]`，第一、二个用例的 day_plans 未变）。

- [ ] **Step 3: 实现 `_apply_search_op`**

替换 `backend/app/graph/nodes/refine.py` 末尾的占位实现：

```python
async def _apply_search_op(state, day_plans, idx, op, constraints) -> list:
    """补检索后局部插入/替换。失败/空 → 降级不改，返回 []。"""
    return []
```

为：

```python
async def _apply_search_op(state, day_plans, idx, op, constraints) -> list:
    """补检索后局部插入/替换受影响天。失败/空 → 降级不改，返回 []。"""
    city = state.get("city", "")
    keywords = (constraints or {}).get("keywords")
    target_day = day_plans[idx].get("day")
    try:
        if op == "change_meal":
            pois = await amap.search_poi(city, keywords or "美食", "餐饮")
            if not pois:
                return []
            day_plans[idx] = _set_meal(day_plans[idx], _poi_to_item(pois[0], "meal"))
        else:  # add / replace 景点
            pois = await amap.search_poi(city, keywords or "热门景点", "风景名胜")
            if not pois:
                return []
            item = _poi_to_item(pois[0], "attraction")
            day_plans[idx] = _add_or_replace_attraction(day_plans[idx], item, replace=(op == "replace"))
    except Exception:  # noqa: BLE001 —— 检索失败降级，不阻断本轮
        return []
    return [target_day]
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd backend && uv run pytest tests/test_refine_search.py -q`
Expected: PASS（换餐厅替换、加景点追加、检索空降级 3 个用例全绿）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/nodes/refine.py backend/tests/test_refine_search.py
git commit -m "feat(m5fix): refine 选择性补检索（换餐厅→餐饮、加/换景点→景点）局部插入" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: 端到端多轮路由验证（换餐厅 / 纯重排跳过 / 改预算）

**Files:**
- Test: `backend/tests/test_m5fix_e2e.py`（新建）

**Interfaces:**
- Consumes: 完整图（Task 1–5）；SSE `session`/`final`/`plan_patch` 事件。
- Produces: 端到端断言：refine 各 op 走对路由、只改受影响天、按需跳过 accommodation/budget。

- [ ] **Step 1: 写端到端测试**

新建 `backend/tests/test_m5fix_e2e.py`：

```python
"""M5 fix 端到端：单一 dispatch_agent 派发 + refine 按 op 选择性重排/补检索/跳过。"""
import json
import re


def _extract(body: str, event: str) -> dict:
    m = re.search(rf"event: {event}\r?\ndata: (.+)", body)
    assert m, f"no {event} event in:\n{body}"
    return json.loads(m.group(1).strip())


def _stub_plan_new(monkeypatch):
    from app.graph.nodes import accommodation as acc, clarify as c, dispatch_agent as d, itinerary as it, summarize as s
    from app.graph.nodes.accommodation import _AccoResult
    from app.graph.nodes.dispatch import NormalizedReq
    from app.graph.nodes.itinerary import DayPlans, DayPlan, PlanItem, Location, DayWeather
    from tests.conftest import make_fake_build_llm

    async def no_gaps(_state, _config=None):
        return []
    monkeypatch.setattr(c, "_evaluate_gaps", no_gaps)
    monkeypatch.setattr(d, "build_llm", make_fake_build_llm(
        structured=NormalizedReq(city="成都", days=2, num_people=2, budget=4000)))
    monkeypatch.setattr(it, "build_llm", make_fake_build_llm(structured=DayPlans(days=[
        DayPlan(day=1, weather=DayWeather(), center=Location(lng=104.0, lat=30.6), items=[
            PlanItem(type="attraction", name="武侯祠", poi_id="B1", location=Location(lng=104.0, lat=30.6)),
            PlanItem(type="meal", name="陈麻婆", poi_id="M1", location=Location(lng=104.0, lat=30.6), cost=80.0)]),
        DayPlan(day=2, weather=DayWeather(), center=Location(lng=104.1, lat=30.7), items=[
            PlanItem(type="attraction", name="杜甫草堂", poi_id="B2", location=Location(lng=104.1, lat=30.7))]),
    ])))
    monkeypatch.setattr(acc, "build_llm", make_fake_build_llm(structured=_AccoResult(assignments=[])))
    monkeypatch.setattr(s, "build_llm", make_fake_build_llm(tokens=["已处理", "完成"]))


def _new_plan(client, monkeypatch):
    _stub_plan_new(monkeypatch)
    first = client.post("/api/chat", json={"message": "成都2天2人预算4000"}).text
    return _extract(first, "session")["thread_id"]


def test_change_meal_only_target_day_and_runs_budget(client, fake_amap, monkeypatch):
    tid = _new_plan(client, monkeypatch)
    fake_amap["search_poi"] = [{"name": "蜀大侠火锅", "poi_id": "M9", "lng": 104.0, "lat": 30.6}]
    body = client.post("/api/chat",
                       json={"message": "把第一天晚餐换成火锅", "thread_id": tid}).text
    patch = _extract(body, "plan_patch")
    final = _extract(body, "final")
    assert patch["changed_days"] == [1]
    meals = [i["name"] for i in final["day_plans"][0]["items"] if i["type"] == "meal"]
    assert meals == ["蜀大侠火锅"]
    assert [i["name"] for i in final["day_plans"][1]["items"]] == ["杜甫草堂"]  # 第二天不动


def test_reorder_skips_accommodation_and_budget(client, fake_amap, monkeypatch):
    tid = _new_plan(client, monkeypatch)

    async def boom(*_a, **_k):
        raise AssertionError("reorder 不应触发检索")
    import app.tools.amap as amap
    monkeypatch.setattr(amap, "search_poi", boom)   # accommodation 若被调用会经 search_poi → 炸

    body = client.post("/api/chat",
                       json={"message": "第一天顺序调整一下", "thread_id": tid}).text
    patch = _extract(body, "plan_patch")
    assert patch["changed_days"] == [1]             # 走到 summarize，未碰 accommodation/budget


def test_change_budget_updates_limit(client, fake_amap, monkeypatch):
    tid = _new_plan(client, monkeypatch)
    body = client.post("/api/chat",
                       json={"message": "预算改成1500", "thread_id": tid}).text
    final = _extract(body, "final")
    assert final["budget"]["limit"] == 1500.0       # change_budget → budget 重新核算
```

- [ ] **Step 2: 运行测试，确认通过**

Run: `cd backend && uv run pytest tests/test_m5fix_e2e.py -q`
Expected: PASS。说明：
- 换餐厅：dispatch_agent 规则判 refine_existing + op=change_meal（含"晚餐""换"）→ refine 调 `restaurants` 检索 → 只改第一天 meal → `route_after_plan`→budget→summarize。
- 纯重排：op=reorder → `route_after_plan`→summarize，**不经过 accommodation**（其 `amap.search_poi` 被打成炸弹也不触发）。
- 改预算：op=change_budget → refine 写 `budget=1500` → `route_after_plan`→budget 核算，`final.budget.limit==1500`。

- [ ] **Step 3: 全量后端测试**

Run: `cd backend && uv run pytest -q`
Expected: 全绿（M1/M2/M4/M5 + M5 fix 全部）。

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_m5fix_e2e.py
git commit -m "test(m5fix): 端到端验证 refine 按 op 选择性重排/补检索/跳过" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: 前端进度标签对齐（dispatch_agent / retrieve）

**Files:**
- Modify: `frontend/src/components/AgentProgress.vue`

**Interfaces:**
- Consumes: 后端 `node_start` 事件的 `node` 名（已由 Task 2 改为 `dispatch_agent`/`retrieve`，并随事件带 `label`）。
- Produces: 进度条本地 `LABELS` 兜底文案与后端节点名一致（去 `intent`/`dispatch`，加 `dispatch_agent`/`retrieve`）。

> SSE 数据契约（`final`/`plan_patch`/`clarify`/`session`）未变，故 `types`、`store`、`useSSE`、`ResultPanel` 无需改动。仅进度条节点标签需对齐。

- [ ] **Step 1: 定位 AgentProgress 的 LABELS**

Run: `cd frontend && grep -n "itinerary\|dispatch\|intent\|LABELS" src/components/AgentProgress.vue`
Expected: 找到 `LABELS` 常量对象（含 `dispatch`/`intent`/`itinerary` 等键）。

- [ ] **Step 2: 更新 LABELS 键**

在 `frontend/src/components/AgentProgress.vue` 的 `LABELS` 对象中：
- 删除 `intent` 与 `dispatch` 两个键（若存在）。
- 加入：

```ts
  dispatch_agent: '判断任务并分发',
  retrieve: '并行检索',
```

（其余键 `clarify`/`memory`/`weather`/`attractions`/`restaurants`/`transport`/`itinerary`/`accommodation`/`budget`/`summarize`/`refine`/`answer`/`memory_update` 保留。）

- [ ] **Step 3: 类型检查通过**

Run: `cd frontend && bun run build`
Expected: 构建成功，无 TS 报错。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AgentProgress.vue
git commit -m "feat(m5fix): 前端进度标签对齐 dispatch_agent/retrieve" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: 文档对齐（设计文档 §3.4/§3.7 + README M5 fix 验收清单）

**Files:**
- Modify: `docs/superpowers/specs/2026-06-19-m5-true-multiturn-conversations-design.md`
- Modify: `backend/README.md`

**Interfaces:**
- Consumes: Task 1–7 落定的拓扑与路由。
- Produces: 设计文档与最新图/代码一致；README 增 M5 fix 验收清单。

- [ ] **Step 1: 更新设计文档节点拓扑**

在 `docs/superpowers/specs/2026-06-19-m5-true-multiturn-conversations-design.md` 的 §3.4「新增节点」处，把原 `memory → intent → {clarify→dispatch→检索…}` 的流程图段落替换为最新拓扑描述（与 [m5-graph-flow.excalidraw](../specs/m5-graph-flow.excalidraw) 一致）：

````markdown
M5 fix 实际落地拓扑（intent + dispatch 物理合并为 dispatch_agent）：

```text
（pending interrupt 时：API 层直接 Command(resume=message) 从 clarify 暂停点恢复，跳过 memory / dispatch_agent）

START → memory → dispatch_agent
  ├─ plan_new → reset_plan_new → clarify ⟲ → retrieve → 并行检索(天气/景点/餐饮/交通)
  │             → itinerary → ◇酒店需重排? ─是→ accommodation ─┐
  │                                          └否─────────────────┤→ ◇预算需重算? ─是→ budget ─┐
  │                                                              └否────────────────────────────┤→ summarize
  │             （budget 超支且 plan_new → 回 itinerary 重排）                                    │
  ├─ refine_existing → refine（旧 day_plans 局部重排 + 按 op 选择性补检索）→ 同上「酒店需重排?/预算需重算?」两判断 → summarize
  └─ qa → answer
  → memory_update → END
```

两个判断为**规则路由**（`route_after_plan` / `route_after_accommodation`），依据 `last_intent` + `refine_request.op`，不额外调用 LLM；op→标志映射见实现计划 Global Constraints 表。
````

并把 §3.7 中「refine 路径不回到 itinerary」一句保留并强化为：「refine 局部重排在 refine 节点内完成，只改受影响天；其后接 `route_after_plan` 两段按需判断，`change_hotel` 才走 accommodation、`needs_budget_recheck` 才走 budget、`reorder` 直达 summarize」。

- [ ] **Step 2: README 增 M5 fix 验收清单**

在 `backend/README.md` 末尾追加：

````markdown
## M5 fix 验收清单

把 M5 编排重构为「单一 dispatch_agent 前置派发 + refine 局部重排 + 住宿/预算按需重排」。

- 拓扑：`START → memory → dispatch_agent ─{plan_new→reset→clarify⟲→retrieve→并行检索→itinerary, refine→refine, qa→answer}`；`itinerary`/`refine → route_after_plan{accommodation,budget,summarize}`；`accommodation → route_after_accommodation{budget,summarize}`；`budget → route_after_budget{itinerary(仅plan_new超支),summarize}`。
- 判断为规则路由（不调 LLM）：`route_after_plan`/`route_after_accommodation` 读 `last_intent` + `refine_request.op`。
- refine 局部重排（async，只改 target_day）：relax/remove/reorder 本地改；change_meal→`restaurants` 检索、add/replace→`attractions` 检索后局部插入；change_budget 改预算上限走 budget；change_hotel 交 accommodation 重排。

### 测试（M5 fix）

```bash
cd backend && uv run pytest -q
```

关键覆盖：`test_dispatch_agent`（合并判意图+解析）、`test_dispatch_topology`（前半拓扑）、`test_need_routing`（两按需路由）、`test_refine_node`（本地 op）、`test_refine_search`（补检索）、`test_m5fix_e2e`（端到端按 op 选择性重排/跳过）。
````

- [ ] **Step 3: 全链路校验**

```bash
cd backend && uv run pytest -q
cd ../frontend && bun run build
```
Expected: 后端全绿；前端构建成功。

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-06-19-m5-true-multiturn-conversations-design.md backend/README.md
git commit -m "docs(m5fix): 设计文档拓扑对齐 + README M5 fix 验收清单" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## 任务依赖

线性依赖，建议顺序执行：

- **Task 1**（dispatch_agent 新建，不接线）→ **Task 2**（接线物理合并 + clarify 写回 + retrieve + 删 intent + 迁移测试）→ **Task 3**（两按需路由 + 后半接线）。前三个完成后图拓扑已全部切换到新架构。
- **Task 4**（refine async + 本地 op）→ **Task 5**（refine 补检索）→ **Task 6**（端到端验证）。
- **Task 7**（前端标签）与 **Task 8**（文档）可在后端绿后并行收尾。

每个 Task 结束都应 `uv run pytest -q` 全绿后再进入下一个；Task 2 是破坏面最大的一步（删节点 + 改 5 个测试文件），务必单独 review。

