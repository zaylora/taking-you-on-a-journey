# M2 核心 Agent 编排 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 M1 已打通的 SSE 流式骨架上接线完整 M2 编排：`clarify`(interrupt 多轮澄清)→ `dispatch`(需求标准化)→ 4 个并行高德检索 Agent → `itinerary`(聚类分天+LLM 填充)→ `summarize`(逐日中文攻略逐字流式)。

**Architecture:** LangGraph `StateGraph` + `MemorySaver` checkpointer，按 `thread_id` 跨请求恢复 interrupt。桥接层 `stream.py` 把 `astream_events(v2)` 翻译为 SSE，并在「流后查 state」判定暂停(clarify)还是完成(final)。高德 Web API 由后端 `tools/amap.py` 代理，Key 不下发前端。前端按 `thread_id` 维护会话态，渲染澄清选项气泡与多节点进度点亮。

**Tech Stack:** Python 3.14 / FastAPI / langgraph 1.2.5 / langchain-core 1.x / httpx / sse-starlette；前端 Vue 3 + Pinia + Element Plus + Vite。

**参考设计文档(实现者可查阅，但本计划的任务 brief 自包含所需代码)：** `docs/superpowers/specs/2026-06-18-m2-core-orchestration-design.md`(下称「设计文档」)。

## Global Constraints

逐条为硬约束，每个任务的需求都隐含包含本节。带 🔬 的来自探针实测(langgraph 1.2.5)。

- 🔬 **Python ≥ 3.11(本项目跑最新的 3.14）**。原因：`interrupt()` 经 contextvar(`get_config()`)取 config，Python 3.10 的 async/executor 下该 contextvar 不传播，必报 `RuntimeError: Called get_config outside of a runnable context`。3.11+ (实测 3.12 与 3.14) 下 async 与 sync 节点的 `interrupt()` 均正常。`.python-version`=3.14，`requires-python=">=3.11"`(floor 是 interrupt 的真实下限)。
- 🔬 **interrupt 暂停干净**：图在 `interrupt()` 处暂停时，`astream_events(v2)` 异步生成器**自然结束、不抛异常**。判定必须用「流后查 state」，不依赖事件流里的 interrupt 帧。
- 🔬 **interrupt 检测取值**：`snap = await GRAPH.aget_state(config)`；`pending = [t.interrupts[0] for t in (snap.tasks or []) if t.interrupts]`；每个元素是 `langgraph.types.Interrupt`，`.value` **正是** `interrupt(...)` 传入的 dict。有 pending 则发 `clarify`(取 `.value`)、**不发 final**；否则发 `final`。
- 🔬 **interrupt 前代码 resume 时重跑**：节点在 resume 时从头重新执行，`interrupt()` 之前的代码会再跑一次(故 clarify 的 gap 评估须用 `temperature=0` 保持确定性)；暂停时该次 `return` **不被应用**。
- 🔬 **token 过滤**：只放行 `ev["metadata"]["langgraph_node"] == "summarize"` 的 `on_chat_model_stream`；其余节点的 LLM token 一律丢弃，防止污染正文。
- **SSE 事件全集与精确 data 形状**(前后端常量必须一致)：
  - `session` `{"thread_id":"<hex>"}` —— 仅新会话首帧发一次。
  - `node_start` `{"node":"attractions","label":"正在检索热门景点…"}` —— label 为友好阶段文案。
  - `token` `{"text":"成"}` —— 仅 summarize。
  - `node_end` `{"node":"attractions"}`。
  - `clarify` `{"field":"budget","question":"预算档位？","options":["经济","舒适","高端"]}` —— options 空数组=自由文本。本轮结束信号之一。
  - `final` `{"answer":"完整攻略文本","day_plans":[...]}` —— 本轮结束信号之二。
  - `error` `{"message":"用户可读错误"}` —— 脱敏，不含 Key/堆栈。
  - **clarify 与 final 互斥**；前端收到任一都停 loading。
- **thread_id**：后端用 `uuid.uuid4().hex` 生成(⚠️ 运行期生成，**不可**放模块顶层)，`session` 首帧下发；前端整会话固定带回。
- **checkpointer**：`MemorySaver()`，`GRAPH = build_graph()` 模块级单例(一个 saver 跨多 thread)。
- **AMAP_WEB_KEY**：启动期 fail-fast(与 LLM Key 一并校验，缺则 `RuntimeError` 退出)。Key 取自 `config.amap_web_key.get_secret_value()`，**绝不下发前端、绝不进日志/SSE**。
- **clarify 轮次上限**：`MAX_CLARIFY_ROUNDS = 4`，超限取兜底直接放行(`clarified=True`)。
- **State 并行写**：4 个检索节点各写独立 key(`weather`/`attractions`/`restaurants`/`transport`)，不写同一 key；`clarify_history` 用 `Annotated[list, operator.add]` reducer 防覆盖；`messages` 用 `add_messages`。
- **节点对缺省 key 容错**：所有节点读 state 一律 `state.get(key, 默认)`，因为新会话 `stream_input` 只给了部分初始字段。
- **降级而非抛**：高德超时/限流/空结果 → tool 层返回兜底值不抛；单个并行节点失败 → 写空/兜底字段不阻断其余；`itinerary` 用已有数据降级排程。
- **summarize 输出简体中文**，按 `day_plans` 逐日渲染。
- **`final.answer` 来源**：读 `snap.values.get("summary","")`(不再累加 token)；故 summarize 必须写 `summary` 字段。
- **测试一律打桩**：对 `build_llm`(及 `with_structured_output`)与 `app.tools.amap.*` 打桩，不依赖真实 Key/网络。
- **day_plans 数据结构**(itinerary 产出 / final 下发 / M3 消费)：
  ```jsonc
  [{
    "day": 1, "date": "2026-07-01",
    "weather": {"text":"多云","temp":"24~31℃","is_rainy": false},
    "center": {"lng":104.06,"lat":30.65},
    "items": [
      {"type":"attraction","name":"武侯祠","poi_id":"B001",
       "location":{"lng":104.04,"lat":30.64},"start":"09:00","end":"11:00","indoor":false,"note":"..."},
      {"type":"meal","name":"陈麻婆豆腐","poi_id":"B002",
       "location":{"lng":104.05,"lat":30.66},"start":"12:00","end":"13:00"},
      {"type":"transport","mode":"地铁","from":"武侯祠","to":"...","note":"..."}
    ]
  }]
  ```
- **M2 不做**(防 scope creep)：地图打点/POI 卡片(M3)、accommodation/budget 节点(M4，保持占位 `return {}` 且不 `add_edge`)、缓存/限流、局部重排/导出(M5)。

## File Structure

**后端新建：**
- `app/tools/amap.py` —— 高德 Web 服务代理(geocode/search_poi/get_weather/plan_route)，httpx + 超时 + 降级。
- `app/graph/nodes/itinerary.py` 内含纯函数 `cluster_by_day`(也可独立 `app/graph/cluster.py`；本计划放 itinerary.py 内，纯函数零依赖)。
- `tests/conftest.py` —— 复用打桩件(FakeStreamingLLM / FakeStructuredLLM / fake_amap)。
- `tests/test_cluster_by_day.py` / `tests/test_clarify_interrupt.py` / `tests/test_dispatch.py` / `tests/test_parallel_retrieval.py` / `tests/test_itinerary.py` / `tests/test_summarize.py` / `tests/test_chat_stream_m2.py`。

**后端修改：**
- `pyproject.toml` / `.python-version`(Python 3.12)；`.env.example`(AMAP_WEB_KEY)。
- `app/core/config.py`(amap_web_key) / `app/core/constants.py`(EVENT_SESSION/EVENT_CLARIFY + NODE_LABELS) / `app/main.py`(fail-fast amap key) / `app/schemas/chat.py`(thread_id)。
- `app/graph/state.py`(启用 M2 字段) / `app/graph/builder.py`(接线 8 节点 + MemorySaver) / `app/graph/stream.py`(session/clarify/resume/token 过滤) / `app/api/chat.py`(透传 thread_id)。
- 节点：`clarify.py`/`dispatch.py`/`weather.py`/`attractions.py`/`restaurants.py`/`transport.py`/`itinerary.py`/`summarize.py`。

**前端修改/新建：**
- `src/types/index.ts` / `src/api/sse.ts` / `src/stores/trip.ts` / `src/composables/useSSE.ts` / `src/components/AgentProgress.vue` / `src/components/MessageList.vue`；新建 `src/components/ClarifyOptions.vue`。

---

### Task 1: Python 3.12 运行时升级(地基，解 interrupt 阻塞)

**Files:**
- Modify: `backend/.python-version`
- Modify: `backend/pyproject.toml`(requires-python)
- Recreate: `backend/.venv`

**Interfaces:**
- Produces: 一个跑在 Python 3.12 上的后端虚拟环境；M1 既有测试全绿(无回归)。后续所有任务都在此环境运行。

- [ ] **Step 1: 改 `.python-version`**

把 `backend/.python-version` 内容整文件替换为：
```
3.14
```

- [ ] **Step 2: 改 `pyproject.toml` 的 requires-python**

把 `requires-python = ">=3.10"` 改为：
```toml
requires-python = ">=3.11"
```

- [ ] **Step 3: 重建 venv 到 3.12**

Run:
```bash
cd backend && rm -rf .venv && uv sync
```
Expected: 成功创建 `.venv`，无解析错误。

- [ ] **Step 4: 验证解释器版本**

Run: `cd backend && uv run python -c "import sys; print(sys.version)"`
Expected: 输出以 `3.14.` 开头。

- [ ] **Step 5: 验证 M1 测试无回归**

Run: `cd backend && uv run pytest -q`
Expected: 既有 `tests/test_chat_stream.py` 全部 PASS。

- [ ] **Step 6: Commit**

```bash
cd backend && git add .python-version pyproject.toml uv.lock
git commit -m "build: M2 升级运行时到 Python 3.12（interrupt 需 contextvar 传播，3.10 不支持）"
```

---

### Task 2: 共享契约 + 测试打桩件(state / constants / config / schema / main / conftest)

**Files:**
- Modify: `backend/app/graph/state.py`
- Modify: `backend/app/core/constants.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/schemas/chat.py`
- Modify: `backend/app/main.py`
- Modify: `backend/.env.example`
- Modify: `backend/tests/test_chat_stream.py`(M1 测试 fixture 补 AMAP 假 Key，因本任务新增 amap fail-fast）
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_contracts.py`

**Interfaces:**
- Produces:
  - `TripState`(TypedDict)新增字段：`city:str, start_date:str, days:int, num_people:int, preferences:dict, budget:float, normalized_req:dict, clarify_history:Annotated[list,add], clarified:bool, clarify_round:int, weather:dict, attractions:list, restaurants:list, transport:dict, daily_centers:list, day_plans:list`。
  - `constants`: `EVENT_SESSION="session"`, `EVENT_CLARIFY="clarify"`, `NODES:set[str]`(8 个节点名), `NODE_LABELS:dict[str,str]`, `MAX_CLARIFY_ROUNDS=4`。
  - `Settings.amap_web_key: SecretStr`。
  - `ChatRequest.thread_id: str | None = None`。
  - `main` 启动 fail-fast 同时校验 LLM Key 与 `amap_web_key`。
  - `conftest.py` 暴露 fixture/helper：`FakeStreamingLLM`、`FakeStructuredLLM`、`make_fake_build_llm(...)`、`fake_amap`(patch `app.tools.amap` 四函数)。

- [ ] **Step 1: 写失败测试 `tests/test_contracts.py`**

```python
from app.core import constants as C
from app.core.config import Settings
from app.schemas.chat import ChatRequest
from app.graph.state import TripState


def test_event_constants_present():
    assert C.EVENT_SESSION == "session"
    assert C.EVENT_CLARIFY == "clarify"
    assert C.MAX_CLARIFY_ROUNDS == 4


def test_node_labels_cover_all_nodes():
    assert C.NODES == {"clarify", "dispatch", "weather", "attractions",
                       "restaurants", "transport", "itinerary", "summarize"}
    for n in C.NODES:
        assert C.NODE_LABELS.get(n)  # 每个节点都有非空中文文案


def test_chat_request_thread_id_optional():
    assert ChatRequest(message="hi").thread_id is None
    assert ChatRequest(message="hi", thread_id="abc").thread_id == "abc"


def test_settings_has_amap_key():
    s = Settings(_env_file=None)
    assert s.amap_web_key.get_secret_value() == ""  # 默认空


def test_tripstate_has_m2_keys():
    keys = TripState.__annotations__
    for k in ("city", "days", "preferences", "clarify_history", "clarified",
              "clarify_round", "weather", "attractions", "restaurants",
              "transport", "daily_centers", "day_plans", "normalized_req"):
        assert k in keys
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_contracts.py -q`
Expected: FAIL(AttributeError/AssertionError，字段/常量尚不存在)。

- [ ] **Step 3: 扩展 `app/graph/state.py`**

```python
"""图状态定义。messages 用 add_messages、clarify_history 用 add，避免多节点/多轮写覆盖。"""
from operator import add
from typing import Annotated

from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class TripState(TypedDict, total=False):
    # —— 沿用 ——
    query: str
    messages: Annotated[list, add_messages]
    summary: str

    # —— 结构化需求（dispatch 标准化产出 + clarify 累积）——
    city: str
    start_date: str
    days: int
    num_people: int
    preferences: dict
    budget: float
    normalized_req: dict

    # —— 需求澄清 ——
    clarify_history: Annotated[list, add]   # [{field, question, options, answer}]
    clarified: bool
    clarify_round: int

    # —— 并行检索产出（各写独立字段，避免写冲突）——
    weather: dict
    attractions: list
    restaurants: list
    transport: dict

    # —— 行程编排产出 ——
    daily_centers: list
    day_plans: list

    # —— M4 预留（注释占位）——
    # hotels: list
    # budget_check: dict
    # retry_count: int
```
> 用 `total=False`：新会话 `stream_input` 只给部分键，节点用 `.get()` 读，TypedDict 不强制全字段。

- [ ] **Step 4: 扩展 `app/core/constants.py`**

在文件末尾追加(保留既有 5 个事件常量)：
```python
EVENT_SESSION = "session"   # data: {"thread_id": "<hex>"} —— 新会话首帧
EVENT_CLARIFY = "clarify"   # data: {"field","question","options"} —— 暂停等澄清

# 图节点全集（桥接层据此过滤 on_chain_start/end 名）
NODES = {"clarify", "dispatch", "weather", "attractions",
         "restaurants", "transport", "itinerary", "summarize"}

# node_start 携带的友好阶段文案（前端进度条展示，不暴露中间 LLM token）
NODE_LABELS = {
    "clarify": "正在理解你的需求…",
    "dispatch": "正在梳理需求要点…",
    "weather": "正在查询目的地天气…",
    "attractions": "正在检索热门景点…",
    "restaurants": "正在挑选餐厅…",
    "transport": "正在规划交通…",
    "itinerary": "正在按顺路编排每日行程…",
    "summarize": "正在生成攻略…",
}

MAX_CLARIFY_ROUNDS = 4   # clarify 自循环轮次上限，超限取兜底放行
```

- [ ] **Step 5: 扩展 `app/core/config.py`**

在 `Settings` 内 `temperature` 字段附近加：
```python
    # 高德 Web 服务（后端代理，Key 不下发前端）
    amap_web_key: SecretStr = SecretStr("")
```

- [ ] **Step 6: 扩展 `app/schemas/chat.py`**

```python
"""请求/响应 schema。"""
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户输入的一句话")
    thread_id: str | None = Field(default=None, description="会话 id；首次为 null，由后端 session 帧下发")
```

- [ ] **Step 7: `app/main.py` fail-fast 增 amap key 校验**

把 lifespan 内校验改为：
```python
    settings = get_settings()
    if not settings.active_api_key():
        raise RuntimeError(
            f"缺少 {settings.llm_provider} 的 API Key，请在 backend/.env 中配置后再启动。"
        )
    if not settings.amap_web_key.get_secret_value():
        raise RuntimeError("缺少 AMAP_WEB_KEY，请在 backend/.env 中配置后再启动。")
    yield
```
并把 `FastAPI(title=...)` 的标题改为 `"Trip Planner Backend (M2)"`。

> ⚠️ 本步新增的 amap fail-fast 会让既有 M1 测试 `tests/test_chat_stream.py` 在启动期崩溃（其 `client` fixture 只设了 `OPENAI_API_KEY`）。同一任务内必须修复：在该 fixture 的 `monkeypatch.setenv("OPENAI_API_KEY", ...)` 之后补一行：
> ```python
>     monkeypatch.setenv("AMAP_WEB_KEY", "amap-test-fake")
> ```
> （此时图仍是 M1 的 dispatch→summarize，clarify 不在图上，故 M1 流式测试无需额外打桩即可通过。）

- [ ] **Step 8: `.env.example` 增高德 Key**

在文件末尾追加：
```bash
# === 高德 Web 服务（后端代理，Key 不下发前端，M2 验收需要）===
AMAP_WEB_KEY=
```

- [ ] **Step 9: 写 `tests/conftest.py` 复用打桩件**

```python
"""复用打桩件：假 LLM（流式 / 结构化）与假高德 tool。所有测试不依赖真实 Key/网络。"""
import pytest
from langchain_core.messages import AIMessageChunk


class FakeStreamingLLM:
    """模拟 build_llm() 返回的可流式 ChatModel，仅实现 astream。"""
    def __init__(self, tokens):
        self._tokens = list(tokens)

    async def astream(self, _messages, config=None, **kw):
        for t in self._tokens:
            yield AIMessageChunk(content=t)


class _StructuredRunnable:
    def __init__(self, result):
        self._result = result

    async def ainvoke(self, *_a, **_k):
        return self._result

    def invoke(self, *_a, **_k):
        return self._result


class FakeStructuredLLM:
    """模拟 build_llm()；with_structured_output(Schema) 返回固定结果的 runnable。"""
    def __init__(self, result):
        self._result = result

    def with_structured_output(self, _schema, **_kw):
        return _StructuredRunnable(self._result)


def make_fake_build_llm(*, tokens=None, structured=None):
    """生成可 monkeypatch 进各节点模块的 build_llm 替身。"""
    def _factory(*_a, **_k):
        if structured is not None:
            return FakeStructuredLLM(structured)
        return FakeStreamingLLM(tokens or ["占位"])
    return _factory


@pytest.fixture
def fake_amap(monkeypatch):
    """把 app.tools.amap 的四个函数 patch 成可控异步返回。返回一个可配置 dict。"""
    import app.tools.amap as amap

    cfg = {
        "geocode": {"lng": 104.06, "lat": 30.65},
        "search_poi": [],
        "get_weather": {"text": "多云", "temp": "24~31℃", "is_rainy": False, "source": "forecast"},
        "plan_route": {},
    }

    async def _geocode(city): return cfg["geocode"]
    async def _search_poi(city, keywords, poi_type="", page_size=20): return cfg["search_poi"]
    async def _get_weather(city): return cfg["get_weather"]
    async def _plan_route(origin, dest, mode="transit"): return cfg["plan_route"]

    monkeypatch.setattr(amap, "geocode", _geocode)
    monkeypatch.setattr(amap, "search_poi", _search_poi)
    monkeypatch.setattr(amap, "get_weather", _get_weather)
    monkeypatch.setattr(amap, "plan_route", _plan_route)
    return cfg


@pytest.fixture
def client(monkeypatch):
    """启动 fail-fast 需要 LLM + 高德 Key：用假 Key 绕过；清 settings 缓存让 lifespan 重读。
    节点级 build_llm/_evaluate_gaps 由各测试自行 patch（运行时解析，无需重建 GRAPH）。
    """
    from fastapi.testclient import TestClient
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    monkeypatch.setenv("AMAP_WEB_KEY", "amap-test-fake")
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.main import app
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()
```

- [ ] **Step 10: 运行测试至全绿**

Run: `cd backend && uv run pytest tests/test_contracts.py -q`
Expected: PASS(5 passed)。conftest 在 import 时不报错。

- [ ] **Step 11: Commit**

```bash
cd backend && git add app/graph/state.py app/core/constants.py app/core/config.py app/schemas/chat.py app/main.py .env.example tests/conftest.py tests/test_contracts.py tests/test_chat_stream.py
git commit -m "feat(m2): 扩展共享契约（state/事件常量/amap key/thread_id）与测试打桩件"
```

---

### Task 3: 高德 tool 层 `app/tools/amap.py`(httpx + 超时 + 降级)

**Files:**
- Create: `backend/app/tools/amap.py`
- Create: `backend/tests/test_amap.py`

**Interfaces:**
- Produces(全部 async，失败/超时/空结果一律降级返回兜底，不抛)：
  - `async def geocode(city: str) -> dict` → `{"lng":float,"lat":float}`；失败 `{}`。
  - `async def search_poi(city: str, keywords: str, poi_type: str = "", page_size: int = 20) -> list[dict]`；每项含 `name/poi_id/lng/lat/address/type`；失败/空 `[]`。
  - `async def get_weather(city: str) -> dict` → `{"text","temp","is_rainy","source"}`；失败降级季节气候文案。
  - `async def plan_route(origin: str, dest: str, mode: str = "transit") -> dict`；失败 `{}`。
- Consumes: `get_settings().amap_web_key.get_secret_value()`。

> 高德 REST 端点：geocode `https://restapi.amap.com/v3/geocode/geo`、POI `https://restapi.amap.com/v3/place/text`、天气 `https://restapi.amap.com/v3/weather/weatherInfo`、路径规划 `https://restapi.amap.com/v3/direction/transit/integrated`(参数细节实现时按高德文档；测试打桩 httpx，不校验真实响应)。

- [ ] **Step 1: 写失败测试 `tests/test_amap.py`(打桩 httpx，验证降级)**

```python
import httpx
import pytest

import app.tools.amap as amap


class _FakeResp:
    def __init__(self, data): self._data = data
    def json(self): return self._data
    def raise_for_status(self): pass


def _patch_client(monkeypatch, *, payload=None, exc=None):
    class _FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k):
            if exc: raise exc
            return _FakeResp(payload)
    monkeypatch.setattr(amap.httpx, "AsyncClient", _FakeClient)


@pytest.mark.asyncio
async def test_geocode_ok(monkeypatch):
    _patch_client(monkeypatch, payload={"status": "1", "geocodes": [{"location": "104.06,30.65"}]})
    assert await amap.geocode("成都") == {"lng": 104.06, "lat": 30.65}


@pytest.mark.asyncio
async def test_geocode_degrades_on_timeout(monkeypatch):
    _patch_client(monkeypatch, exc=httpx.TimeoutException("t"))
    assert await amap.geocode("成都") == {}


@pytest.mark.asyncio
async def test_search_poi_degrades_on_error(monkeypatch):
    _patch_client(monkeypatch, exc=httpx.ConnectError("x"))
    assert await amap.search_poi("成都", "景点", "风景名胜") == []


@pytest.mark.asyncio
async def test_get_weather_degrades_to_climate(monkeypatch):
    _patch_client(monkeypatch, exc=httpx.TimeoutException("t"))
    w = await amap.get_weather("成都")
    assert w["source"] == "climate" and "is_rainy" in w
```
> 需要 pytest 支持 async：在 `pyproject.toml` 的 `[dependency-groups] dev` 加 `pytest-asyncio`，并在 `[tool.pytest.ini_options]` 加 `asyncio_mode = "auto"`(本步顺带做；或在每个 async 测试加 `@pytest.mark.asyncio`，已加)。实现者执行：`cd backend && uv add --dev pytest-asyncio` 并设 `asyncio_mode="auto"`。

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_amap.py -q`
Expected: FAIL(模块 `app.tools.amap` 无 geocode 等)。

- [ ] **Step 3: 实现 `app/tools/amap.py`**

```python
"""高德 Web 服务代理：统一 httpx.AsyncClient + 5s 超时 + 失败降级（不抛）。
Key 取自 config.amap_web_key，绝不下发前端、绝不进日志/SSE。
"""
import httpx

from app.core.config import get_settings

_BASE = "https://restapi.amap.com/v3"
_TIMEOUT = 5.0


def _key() -> str:
    return get_settings().amap_web_key.get_secret_value()


async def geocode(city: str) -> dict:
    """城市 → 中心坐标 {lng,lat}。失败降级 {}。"""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{_BASE}/geocode/geo", params={"key": _key(), "address": city})
            r.raise_for_status()
            data = r.json()
        loc = (data.get("geocodes") or [{}])[0].get("location")
        if not loc:
            return {}
        lng, lat = loc.split(",")
        return {"lng": float(lng), "lat": float(lat)}
    except Exception:  # noqa: BLE001 —— 降级
        return {}


async def search_poi(city: str, keywords: str, poi_type: str = "", page_size: int = 20) -> list[dict]:
    """景点/餐厅候选。每项 name/poi_id/lng/lat/address/type。失败/空 []。"""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{_BASE}/place/text", params={
                "key": _key(), "city": city, "keywords": keywords,
                "types": poi_type, "offset": page_size, "citylimit": "true",
            })
            r.raise_for_status()
            data = r.json()
        out = []
        for p in data.get("pois", []) or []:
            loc = (p.get("location") or "").split(",")
            if len(loc) != 2:
                continue
            out.append({
                "name": p.get("name", ""), "poi_id": p.get("id", ""),
                "lng": float(loc[0]), "lat": float(loc[1]),
                "address": p.get("address", ""), "type": p.get("type", ""),
            })
        return out
    except Exception:  # noqa: BLE001
        return []


async def get_weather(city: str) -> dict:
    """实时+预报；失败/远期降级季节气候文案。{text,temp,is_rainy,source}。"""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{_BASE}/weather/weatherInfo", params={
                "key": _key(), "city": city, "extensions": "all",
            })
            r.raise_for_status()
            data = r.json()
        casts = data.get("forecasts", [{}])[0].get("casts") or []
        if not casts:
            raise ValueError("no forecast")
        today = casts[0]
        text = today.get("dayweather", "")
        return {
            "text": text,
            "temp": f"{today.get('nighttemp','')}~{today.get('daytemp','')}℃",
            "is_rainy": "雨" in text,
            "source": "forecast",
        }
    except Exception:  # noqa: BLE001 —— 降级季节气候
        return {"text": "以当季气候为准", "temp": "", "is_rainy": False, "source": "climate"}


async def plan_route(origin: str, dest: str, mode: str = "transit") -> dict:
    """大交通/市内交通方案；失败降级 {}。"""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{_BASE}/direction/transit/integrated", params={
                "key": _key(), "origin": origin, "destination": dest,
            })
            r.raise_for_status()
            return r.json().get("route", {}) or {}
    except Exception:  # noqa: BLE001
        return {}
```

- [ ] **Step 4: 运行测试至全绿**

Run: `cd backend && uv run pytest tests/test_amap.py -q`
Expected: PASS(4 passed)。

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/tools/amap.py tests/test_amap.py pyproject.toml uv.lock
git commit -m "feat(m2): 新增高德 tool 层（geocode/poi/weather/route，超时+降级）"
```

---

### Task 4: 纯函数 `cluster_by_day` 聚类分天

**Files:**
- Modify: `backend/app/graph/nodes/itinerary.py`(先只加纯函数，节点本体在 Task 8)
- Create: `backend/tests/test_cluster_by_day.py`

**Interfaces:**
- Produces: `def cluster_by_day(points: list[dict], days: int) -> list[list[dict]]` —— 纯函数、零依赖(仅 `math`)。输入每项含 `lng/lat`；输出 `days` 个簇，每天点数尽量均衡，簇内按最近邻顺路排序。边界：`points` 空 → 返回 `days` 个空列表；`len(points) < days` → 部分天为空但长度恒为 `days`；`days <= 0` → 视为 1。

- [ ] **Step 1: 写失败测试 `tests/test_cluster_by_day.py`**

```python
from app.graph.nodes.itinerary import cluster_by_day


def _pt(name, lng, lat): return {"name": name, "lng": lng, "lat": lat}


def test_returns_exactly_days_buckets():
    pts = [_pt(f"p{i}", 104.0 + i * 0.01, 30.6 + i * 0.01) for i in range(9)]
    res = cluster_by_day(pts, 3)
    assert len(res) == 3
    assert sum(len(b) for b in res) == 9


def test_balanced_counts():
    pts = [_pt(f"p{i}", 104.0 + i * 0.01, 30.6) for i in range(10)]
    counts = sorted(len(b) for b in cluster_by_day(pts, 3))
    assert counts[-1] - counts[0] <= 1  # 最多差 1，均衡


def test_empty_points():
    assert cluster_by_day([], 3) == [[], [], []]


def test_fewer_points_than_days():
    res = cluster_by_day([_pt("a", 104.0, 30.6)], 3)
    assert len(res) == 3 and sum(len(b) for b in res) == 1


def test_days_non_positive_treated_as_one():
    res = cluster_by_day([_pt("a", 104.0, 30.6), _pt("b", 104.1, 30.7)], 0)
    assert len(res) == 1 and len(res[0]) == 2


def test_intra_cluster_nearest_neighbor_order():
    # 一条直线上的点应按顺序串起来（首点固定后逐个最近邻）
    pts = [_pt("a", 104.00, 30.6), _pt("c", 104.20, 30.6), _pt("b", 104.10, 30.6)]
    res = cluster_by_day(pts, 1)[0]
    xs = [p["lng"] for p in res]
    assert xs == sorted(xs) or xs == sorted(xs, reverse=True)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_cluster_by_day.py -q`
Expected: FAIL(`cannot import name cluster_by_day`)。

- [ ] **Step 3: 在 `app/graph/nodes/itinerary.py` 顶部实现纯函数**

(本任务只写纯函数 + 文件骨架；节点本体 Task 8 再补，先保留占位 `itinerary`。)
```python
"""itinerary 节点：cluster_by_day 聚类分天（纯函数） + LLM 填充 day_plans（Task 8）。"""
import math


def _dist(a: dict, b: dict) -> float:
    return math.hypot(a.get("lng", 0.0) - b.get("lng", 0.0),
                      a.get("lat", 0.0) - b.get("lat", 0.0))


def cluster_by_day(points: list[dict], days: int) -> list[list[dict]]:
    """手写贪心：按到城市中心的方位角排序 → 均衡切 days 段 → 段内最近邻顺路。
    纯函数、零依赖。接口固定，未来可替换为 KMeans 而不动调用方。
    """
    days = max(1, days)
    buckets: list[list[dict]] = [[] for _ in range(days)]
    if not points:
        return buckets

    # 城市中心 = 质心
    cx = sum(p.get("lng", 0.0) for p in points) / len(points)
    cy = sum(p.get("lat", 0.0) for p in points) / len(points)

    # 按方位角排序，使同方向的点相邻，便于「顺路」分天
    ordered = sorted(points, key=lambda p: math.atan2(p.get("lat", 0.0) - cy,
                                                       p.get("lng", 0.0) - cx))

    # 均衡切片：前 (n % days) 段各多 1 个
    n = len(ordered)
    base, extra = divmod(n, days)
    idx = 0
    for d in range(days):
        size = base + (1 if d < extra else 0)
        seg = ordered[idx:idx + size]
        idx += size
        buckets[d] = _nearest_neighbor_order(seg)
    return buckets


def _nearest_neighbor_order(seg: list[dict]) -> list[dict]:
    if not seg:
        return []
    remaining = list(seg)
    # 起点：经纬度字典序最小的「端点」（确定性；共线时保证单调顺路，不从中间起步）
    cur = min(remaining, key=lambda p: (p.get("lng", 0.0), p.get("lat", 0.0)))
    remaining.remove(cur)
    route = [cur]
    while remaining:
        nxt = min(remaining, key=lambda p: _dist(p, route[-1]))
        remaining.remove(nxt)
        route.append(nxt)
    return route


async def itinerary(state, config):
    return {}  # TODO(Task 8): 聚类 + LLM 填充 day_plans
```

- [ ] **Step 4: 运行测试至全绿**

Run: `cd backend && uv run pytest tests/test_cluster_by_day.py -q`
Expected: PASS(6 passed)。

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/graph/nodes/itinerary.py tests/test_cluster_by_day.py
git commit -m "feat(m2): cluster_by_day 纯函数（方位角均衡分天+簇内最近邻顺路）"
```

---

### Task 5: `clarify` 节点(interrupt 多轮澄清) + 路由

**Files:**
- Modify: `backend/app/graph/nodes/clarify.py`
- Create: `backend/tests/test_clarify_node.py`

**Interfaces:**
- Produces:
  - `async def clarify(state) -> dict`：LLM 结构化评估缺口；无缺口或 `clarify_round >= MAX_CLARIFY_ROUNDS` → `{"clarified": True}`；有缺口 → `interrupt({"field","question","options"})`，resume 后追加 `clarify_history` 并 `{"clarified": False, "clarify_round": round+1}`。
  - `def route_after_clarify(state) -> str`：`"dispatch" if state.get("clarified") else "clarify"`。
  - 内部 pydantic schema `ClarifyGaps`(供结构化输出 + 测试打桩)：`gaps: list[Gap]`，`Gap{field:str, question:str, options:list[str]}`。
- Consumes: `build_llm`(本模块 import，便于 monkeypatch)、`MAX_CLARIFY_ROUNDS`。

> 关键设计：clarify 只管 `clarify_history`/`clarified`/`clarify_round`，**不**直接解析进 city/days(交给 dispatch 标准化)。gap 评估读 `query + clarify_history`，temperature=0 保持确定(应对 resume 重跑)。

- [ ] **Step 1: 写失败测试 `tests/test_clarify_node.py`**

```python
import pytest
from app.graph.nodes import clarify as clarify_mod
from app.graph.nodes.clarify import route_after_clarify, ClarifyGaps, Gap


def test_route_after_clarify():
    assert route_after_clarify({"clarified": True}) == "dispatch"
    assert route_after_clarify({"clarified": False}) == "clarify"
    assert route_after_clarify({}) == "clarify"


@pytest.mark.asyncio
async def test_no_gaps_passes_through(monkeypatch):
    from tests.conftest import make_fake_build_llm
    monkeypatch.setattr(clarify_mod, "build_llm",
                        make_fake_build_llm(structured=ClarifyGaps(gaps=[])))
    out = await clarify_mod.clarify({"query": "成都3天2人爱吃辣预算2000", "clarify_round": 0})
    assert out == {"clarified": True}


@pytest.mark.asyncio
async def test_round_cap_forces_passthrough(monkeypatch):
    from tests.conftest import make_fake_build_llm
    # 即使 LLM 还想追问，到达上限也直接放行
    monkeypatch.setattr(clarify_mod, "build_llm", make_fake_build_llm(
        structured=ClarifyGaps(gaps=[Gap(field="budget", question="预算？", options=[])])))
    out = await clarify_mod.clarify({"query": "x", "clarify_round": 4})
    assert out == {"clarified": True}
```
> interrupt 本身的暂停/恢复在 Task 11 的端到端测试覆盖(需 checkpointer + TestClient)；本任务单测只覆盖「无缺口放行」「轮次兜底」「路由」三条不触发 interrupt 的分支。

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_clarify_node.py -q`
Expected: FAIL(导入 `ClarifyGaps`/`Gap`/`route_after_clarify` 失败)。

- [ ] **Step 3: 实现 `app/graph/nodes/clarify.py`**

```python
"""clarify 节点：interrupt 多轮需求澄清。
- LLM structured output 评估 (query + clarify_history) 找缺口。
- 无缺口 / 轮次到顶 → clarified=True 放行。
- 有缺口 → interrupt 抛出 {field,question,options}，resume 后写回 clarify_history。
⚠️ interrupt 前的评估在 resume 时会重跑，故 temperature=0 保持确定性。
"""
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from app.core.constants import MAX_CLARIFY_ROUNDS
from app.llm.factory import build_llm

_SYS = (
    "你是旅行需求澄清助手。判断用户需求中仍缺失、影响行程规划的关键要素"
    "（如城市、天数、人数、出发日期、预算档位、偏好）。只针对真正缺失的要素提问，"
    "每个缺口给一个简短中文问题；若是档位/单选类给 options，开放式问题 options 为空数组。"
    "若信息已足够规划，返回空 gaps。"
)


class Gap(BaseModel):
    field: str = Field(description="缺失要素字段名，如 city/days/budget")
    question: str = Field(description="向用户提出的简短中文问题")
    options: list[str] = Field(default_factory=list, description="可选项；开放式问题为空")


class ClarifyGaps(BaseModel):
    gaps: list[Gap] = Field(default_factory=list)


async def _evaluate_gaps(state) -> list[Gap]:
    llm = build_llm(temperature=0).with_structured_output(ClarifyGaps)
    history = state.get("clarify_history", [])
    answered = "；".join(f"{h['field']}={h.get('answer','')}" for h in history) or "（无）"
    prompt = [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": f"原始需求：{state.get('query','')}\n已澄清：{answered}"},
    ]
    result = await llm.ainvoke(prompt)
    return result.gaps


async def clarify(state) -> dict:
    rnd = state.get("clarify_round", 0)
    if rnd >= MAX_CLARIFY_ROUNDS:
        return {"clarified": True}
    gaps = await _evaluate_gaps(state)
    if not gaps:
        return {"clarified": True}
    g = gaps[0]
    payload = {"field": g.field, "question": g.question, "options": g.options}
    answer = interrupt(payload)  # 暂停；resume 后 answer = Command(resume=...) 的值
    return {
        "clarify_history": [{**payload, "answer": answer}],
        "clarify_round": rnd + 1,
        "clarified": False,
    }


def route_after_clarify(state) -> str:
    return "dispatch" if state.get("clarified") else "clarify"
```

- [ ] **Step 4: 运行测试至全绿**

Run: `cd backend && uv run pytest tests/test_clarify_node.py -q`
Expected: PASS(3 passed)。

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/graph/nodes/clarify.py tests/test_clarify_node.py
git commit -m "feat(m2): clarify 节点（interrupt 多轮澄清+轮次兜底）与路由"
```

---

### Task 6: `dispatch` 节点升级(需求标准化 → normalized_req)

**Files:**
- Modify: `backend/app/graph/nodes/dispatch.py`
- Create: `backend/tests/test_dispatch.py`

**Interfaces:**
- Produces: `async def dispatch(state) -> dict`：LLM 结构化把 `query + clarify_history` 整理为 `NormalizedReq{city,start_date,days,num_people,preferences:dict,budget:float}`，回填顶层结构化字段 + `normalized_req`(dict 快照) + 追加 user message。
- Consumes: `build_llm`(本模块 import)。
- schema `NormalizedReq`(pydantic) 供结构化输出 + 测试打桩。

- [ ] **Step 1: 写失败测试 `tests/test_dispatch.py`**

```python
import pytest
from app.graph.nodes import dispatch as d_mod
from app.graph.nodes.dispatch import NormalizedReq


@pytest.mark.asyncio
async def test_dispatch_fills_top_level_fields(monkeypatch):
    from tests.conftest import make_fake_build_llm
    req = NormalizedReq(city="成都", start_date="2026-07-01", days=3, num_people=2,
                        preferences={"food": "辣"}, budget=2000.0)
    monkeypatch.setattr(d_mod, "build_llm", make_fake_build_llm(structured=req))
    out = await d_mod.dispatch({"query": "成都3天2人爱吃辣预算2000", "clarify_history": []})
    assert out["city"] == "成都" and out["days"] == 3 and out["num_people"] == 2
    assert out["normalized_req"]["city"] == "成都"
    assert out["messages"]  # 追加了消息
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_dispatch.py -q`
Expected: FAIL。

- [ ] **Step 3: 实现 `app/graph/nodes/dispatch.py`**

```python
"""dispatch 节点（M2 升级）：把 query + clarify_history 标准化为结构化需求。"""
from pydantic import BaseModel, Field

from app.llm.factory import build_llm

_SYS = (
    "把用户的旅行需求整理为结构化字段。缺失项用合理默认：days 默认 3、num_people 默认 1、"
    "budget 默认 0（表示未指定）、start_date 缺失留空字符串。preferences 用键值对概括偏好。"
)


class NormalizedReq(BaseModel):
    city: str = ""
    start_date: str = ""
    days: int = 3
    num_people: int = 1
    preferences: dict = Field(default_factory=dict)
    budget: float = 0.0


async def dispatch(state) -> dict:
    llm = build_llm(temperature=0).with_structured_output(NormalizedReq)
    history = state.get("clarify_history", [])
    answered = "；".join(f"{h['field']}={h.get('answer','')}" for h in history) or "（无）"
    req = await llm.ainvoke([
        {"role": "system", "content": _SYS},
        {"role": "user", "content": f"原始需求：{state.get('query','')}\n已澄清：{answered}"},
    ])
    data = req.model_dump()
    return {
        **data,
        "normalized_req": data,
        "messages": [{"role": "user", "content": state.get("query", "")}],
    }
```

- [ ] **Step 4: 运行测试至全绿**

Run: `cd backend && uv run pytest tests/test_dispatch.py -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/graph/nodes/dispatch.py tests/test_dispatch.py
git commit -m "feat(m2): dispatch 升级为需求标准化（normalized_req + 顶层字段回填）"
```

---

### Task 7: 4 个并行检索节点(weather / attractions / restaurants / transport)

**Files:**
- Modify: `backend/app/graph/nodes/weather.py`
- Modify: `backend/app/graph/nodes/attractions.py`
- Modify: `backend/app/graph/nodes/restaurants.py`
- Modify: `backend/app/graph/nodes/transport.py`
- Create: `backend/tests/test_parallel_retrieval.py`

**Interfaces:**
- Produces(均 `async def f(state, config) -> dict`，各写独立 key，失败降级写兜底，不抛)：
  - `weather(state, config)` → `{"weather": dict}`(调 `amap.get_weather(city)`)。
  - `attractions(state, config)` → `{"attractions": list}`(`amap.search_poi(city, 偏好关键词, "风景名胜")`；候选非空时可 LLM 按偏好筛选/排序，本任务先直接用 POI 列表，LLM 筛选可选)。
  - `restaurants(state, config)` → `{"restaurants": list}`(`amap.search_poi(city, 饮食偏好, "餐饮")`)。
  - `transport(state, config)` → `{"transport": dict}`(`amap.plan_route(...)`，无明确起终点时返回 `{}`)。
- Consumes: `app.tools.amap`(模块 import，测试用 `fake_amap` fixture patch)。

- [ ] **Step 1: 写失败测试 `tests/test_parallel_retrieval.py`**

```python
import pytest
from app.graph.nodes.weather import weather
from app.graph.nodes.attractions import attractions
from app.graph.nodes.restaurants import restaurants
from app.graph.nodes.transport import transport


@pytest.mark.asyncio
async def test_each_node_writes_its_field(fake_amap):
    fake_amap["search_poi"] = [{"name": "武侯祠", "poi_id": "B1", "lng": 104.0, "lat": 30.6,
                                "address": "", "type": "风景名胜"}]
    st = {"city": "成都", "preferences": {"food": "辣"}, "days": 3}
    assert "weather" in await weather(st, None)
    a = await attractions(st, None)
    assert a["attractions"][0]["name"] == "武侯祠"
    assert "restaurants" in await restaurants(st, None)
    assert "transport" in await transport(st, None)


@pytest.mark.asyncio
async def test_single_node_failure_degrades_not_raises(fake_amap, monkeypatch):
    import app.tools.amap as amap
    async def _boom(*a, **k): raise RuntimeError("amap down")
    monkeypatch.setattr(amap, "search_poi", _boom)
    out = await attractions({"city": "成都", "preferences": {}}, None)
    assert out == {"attractions": []}  # 降级空列表，不抛
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_parallel_retrieval.py -q`
Expected: FAIL(节点目前是占位 `return {}`)。

- [ ] **Step 3: 实现 4 个节点**

`app/graph/nodes/weather.py`:
```python
"""weather 节点：调高德天气，失败由 tool 层降级。"""
from app.tools import amap


async def weather(state, config) -> dict:
    return {"weather": await amap.get_weather(state.get("city", ""))}
```

`app/graph/nodes/attractions.py`:
```python
"""attractions 节点：高德 POI 检索景点。失败降级空列表，不阻断并行。"""
from app.tools import amap


async def attractions(state, config) -> dict:
    city = state.get("city", "")
    prefs = state.get("preferences", {}) or {}
    keywords = prefs.get("travel") or prefs.get("theme") or "热门景点"
    try:
        pois = await amap.search_poi(city, keywords, "风景名胜")
    except Exception:  # noqa: BLE001 —— 单节点降级，不阻断其余并行
        pois = []
    return {"attractions": pois}
```

`app/graph/nodes/restaurants.py`:
```python
"""restaurants 节点：高德 POI 检索餐饮。失败降级空列表。"""
from app.tools import amap


async def restaurants(state, config) -> dict:
    city = state.get("city", "")
    prefs = state.get("preferences", {}) or {}
    keywords = prefs.get("food") or "美食"
    try:
        pois = await amap.search_poi(city, keywords, "餐饮")
    except Exception:  # noqa: BLE001
        pois = []
    return {"restaurants": pois}
```

`app/graph/nodes/transport.py`:
```python
"""transport 节点：高德路径规划。无明确起终点则返回空，由 itinerary 降级。"""
from app.tools import amap


async def transport(state, config) -> dict:
    city = state.get("city", "")
    try:
        route = await amap.plan_route(city, city) if city else {}
    except Exception:  # noqa: BLE001
        route = {}
    return {"transport": route}
```

- [ ] **Step 4: 运行测试至全绿**

Run: `cd backend && uv run pytest tests/test_parallel_retrieval.py -q`
Expected: PASS(2 passed)。

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/graph/nodes/weather.py app/graph/nodes/attractions.py app/graph/nodes/restaurants.py app/graph/nodes/transport.py tests/test_parallel_retrieval.py
git commit -m "feat(m2): 4 个并行检索节点（天气/景点/餐厅/交通，单点失败降级）"
```

---

### Task 8: `itinerary` 节点(聚类分天 + LLM 填充 day_plans)

**Files:**
- Modify: `backend/app/graph/nodes/itinerary.py`(补节点本体，纯函数已在 Task 4)
- Create: `backend/tests/test_itinerary.py`

**Interfaces:**
- Produces: `async def itinerary(state, config) -> dict` → `{"daily_centers": list, "day_plans": list}`，`day_plans` 结构符合 Global Constraints 的 schema。流程：`cluster_by_day(attractions, days)` → 雨天(weather.is_rainy)室外项标注 → LLM structured output 按 clusters+restaurants+transport+weather 填充每日时间线/描述/餐厅就近分配。
- Consumes: `cluster_by_day`(同模块)、`build_llm`(本模块 import)。
- schema `DayPlans`(pydantic，嵌套 `DayPlan` / `PlanItem` / `Location` / `DayWeather`) 供结构化输出 + 测试打桩。

- [ ] **Step 1: 写失败测试 `tests/test_itinerary.py`**

```python
import pytest
from app.graph.nodes import itinerary as it_mod
from app.graph.nodes.itinerary import DayPlans, DayPlan, PlanItem, Location, DayWeather


@pytest.mark.asyncio
async def test_itinerary_produces_day_plans(monkeypatch):
    from tests.conftest import make_fake_build_llm
    fake = DayPlans(days=[DayPlan(
        day=1, date="2026-07-01",
        weather=DayWeather(text="多云", temp="24~31℃", is_rainy=False),
        center=Location(lng=104.06, lat=30.65),
        items=[PlanItem(type="attraction", name="武侯祠", poi_id="B1",
                        location=Location(lng=104.04, lat=30.64),
                        start="09:00", end="11:00", indoor=False, note="三国文化")],
    )])
    monkeypatch.setattr(it_mod, "build_llm", make_fake_build_llm(structured=fake))
    state = {"days": 1, "attractions": [{"name": "武侯祠", "poi_id": "B1", "lng": 104.04, "lat": 30.64}],
             "restaurants": [], "transport": {}, "weather": {"is_rainy": False}}
    out = await it_mod.itinerary(state, None)
    dp = out["day_plans"]
    assert dp[0]["day"] == 1
    assert dp[0]["items"][0]["name"] == "武侯祠"
    assert "center" in dp[0]
    assert len(out["daily_centers"]) == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_itinerary.py -q`
Expected: FAIL(schema/节点未实现)。

- [ ] **Step 3: 在 `app/graph/nodes/itinerary.py` 补 schema 与节点本体**

(保留 Task 4 的 `cluster_by_day`/`_dist`/`_nearest_neighbor_order`；删除占位 `itinerary`，替换为真实现。)
```python
from pydantic import BaseModel, Field
from app.llm.factory import build_llm


class Location(BaseModel):
    lng: float = 0.0
    lat: float = 0.0


class DayWeather(BaseModel):
    text: str = ""
    temp: str = ""
    is_rainy: bool = False


class PlanItem(BaseModel):
    type: str                       # attraction | meal | transport
    name: str = ""
    poi_id: str = ""
    location: Location = Field(default_factory=Location)
    start: str = ""
    end: str = ""
    indoor: bool = False
    note: str = ""
    mode: str = ""                  # transport 用
    from_: str = Field(default="", alias="from")
    to: str = ""

    model_config = {"populate_by_name": True}


class DayPlan(BaseModel):
    day: int
    date: str = ""
    weather: DayWeather = Field(default_factory=DayWeather)
    center: Location = Field(default_factory=Location)
    items: list[PlanItem] = Field(default_factory=list)


class DayPlans(BaseModel):
    days: list[DayPlan] = Field(default_factory=list)


_SYS = (
    "你是行程编排助手。给定每天的景点簇、餐厅候选、交通与天气，为每天安排合理的时间线："
    "上午/下午景点、午餐/晚餐就近分配餐厅、必要的市内交通。雨天优先室内项。"
    "输出严格符合给定结构（含每项的 location 经纬度，沿用输入坐标）。"
)


async def itinerary(state, config) -> dict:
    days = state.get("days", 3) or 3
    clusters = cluster_by_day(state.get("attractions", []) or [], days)
    daily_centers = []
    for c in clusters:
        if c:
            cx = sum(p.get("lng", 0.0) for p in c) / len(c)
            cy = sum(p.get("lat", 0.0) for p in c) / len(c)
        else:
            cx = cy = 0.0
        daily_centers.append({"lng": cx, "lat": cy})

    llm = build_llm(temperature=0).with_structured_output(DayPlans)
    payload = {
        "days": days,
        "clusters": clusters,
        "restaurants": state.get("restaurants", []),
        "transport": state.get("transport", {}),
        "weather": state.get("weather", {}),
        "start_date": state.get("start_date", ""),
    }
    result = await llm.ainvoke([
        {"role": "system", "content": _SYS},
        {"role": "user", "content": str(payload)},
    ])
    return {
        "daily_centers": daily_centers,
        "day_plans": [d.model_dump(by_alias=True) for d in result.days],
    }
```

- [ ] **Step 4: 运行测试至全绿**

Run: `cd backend && uv run pytest tests/test_itinerary.py tests/test_cluster_by_day.py -q`
Expected: PASS(全部)。

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/graph/nodes/itinerary.py tests/test_itinerary.py
git commit -m "feat(m2): itinerary 节点（聚类分天+LLM 结构化填充 day_plans）"
```

---

### Task 9: `summarize` 节点升级(按 day_plans 渲染逐日中文攻略，逐字流式)

**Files:**
- Modify: `backend/app/graph/nodes/summarize.py`
- Create: `backend/tests/test_summarize.py`

**Interfaces:**
- Produces: `async def summarize(state, config) -> dict` → `{"messages":[AIMessage], "summary": text}`；从 `day_plans` 构造中文 prompt，`build_llm().astream(..., config=config)` 逐字流式(保持 M1 实测结论：async + 透传 config)。无 day_plans 时降级用 query 文本。
- Consumes: `build_llm`、`state["day_plans"]`。

- [ ] **Step 1: 写失败测试 `tests/test_summarize.py`**

```python
import pytest
from app.graph.nodes import summarize as s_mod


@pytest.mark.asyncio
async def test_summarize_streams_from_day_plans(monkeypatch):
    from tests.conftest import make_fake_build_llm
    monkeypatch.setattr(s_mod, "build_llm",
                        make_fake_build_llm(tokens=["第一天", "：武侯祠"]))
    state = {"day_plans": [{"day": 1, "items": [{"type": "attraction", "name": "武侯祠"}]}],
             "query": "成都3天"}
    out = await s_mod.summarize(state, None)
    assert out["summary"] == "第一天：武侯祠"
    assert out["messages"][0].content == "第一天：武侯祠"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_summarize.py -q`
Expected: FAIL(当前 summarize 读 messages，不读 day_plans)。

- [ ] **Step 3: 实现 `app/graph/nodes/summarize.py`**

```python
"""summarize 节点（M2 升级）：按 day_plans 渲染逐日简体中文攻略，逐字流式。
⚠️ 必须 async + 接收 config + astream(..., config=config)，token 方能冒泡（M1 实测结论）。
"""
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from app.llm.factory import build_llm

_SYS = "你是旅行攻略撰写助手。请用简体中文，按天输出清晰、可读的逐日行程攻略，语气友好实用。"


async def summarize(state: dict, config: RunnableConfig) -> dict:
    day_plans = state.get("day_plans") or []
    if day_plans:
        user = f"请根据以下结构化逐日行程，写成中文攻略：\n{day_plans}"
    else:
        user = f"请根据用户需求给出中文旅行建议：{state.get('query', '')}"
    parts: list[str] = []
    async for chunk in build_llm().astream(
        [{"role": "system", "content": _SYS}, {"role": "user", "content": user}],
        config=config,
    ):
        if chunk.content:
            parts.append(chunk.content)
    text = "".join(parts)
    return {"messages": [AIMessage(content=text)], "summary": text}
```

- [ ] **Step 4: 运行测试至全绿**

Run: `cd backend && uv run pytest tests/test_summarize.py -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/graph/nodes/summarize.py tests/test_summarize.py
git commit -m "feat(m2): summarize 升级为按 day_plans 渲染逐日中文攻略"
```

---

### Task 10: `builder.py` 接线完整 M2 图 + MemorySaver

**Files:**
- Modify: `backend/app/graph/builder.py`
- Create: `backend/tests/test_builder.py`

**Interfaces:**
- Produces: `build_graph()` 编译出含 8 节点的图：`START→clarify`，条件边 `route_after_clarify {clarify→clarify, dispatch→dispatch}`，`dispatch→{weather,attractions,restaurants,transport}` 各 `→itinerary`，`itinerary→summarize→END`，`compile(checkpointer=MemorySaver())`。`accommodation`/`budget` 不接线。
- Consumes: 全部 8 个节点 + `route_after_clarify`。

- [ ] **Step 1: 写失败测试 `tests/test_builder.py`**

```python
from app.graph.builder import build_graph


def test_graph_compiles_with_checkpointer():
    g = build_graph()
    assert g.checkpointer is not None  # MemorySaver 已挂


def test_graph_has_all_m2_nodes():
    g = build_graph()
    nodes = set(g.get_graph().nodes.keys())
    for n in ("clarify", "dispatch", "weather", "attractions",
              "restaurants", "transport", "itinerary", "summarize"):
        assert n in nodes
    # 占位节点不接线
    assert "accommodation" not in nodes and "budget" not in nodes
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_builder.py -q`
Expected: FAIL(当前图只有 dispatch/summarize)。

- [ ] **Step 3: 实现 `app/graph/builder.py`**

```python
"""图构建（M2）：clarify(interrupt 自循环) → dispatch → 4 并行检索 → itinerary → summarize。
compile(checkpointer=MemorySaver())：带 thread_id，interrupt 跨请求恢复。
"""
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.graph.state import TripState
from app.graph.nodes.clarify import clarify, route_after_clarify
from app.graph.nodes.dispatch import dispatch
from app.graph.nodes.weather import weather
from app.graph.nodes.attractions import attractions
from app.graph.nodes.restaurants import restaurants
from app.graph.nodes.transport import transport
from app.graph.nodes.itinerary import itinerary
from app.graph.nodes.summarize import summarize


def build_graph():
    g = StateGraph(TripState)
    for name, fn in [
        ("clarify", clarify), ("dispatch", dispatch),
        ("weather", weather), ("attractions", attractions),
        ("restaurants", restaurants), ("transport", transport),
        ("itinerary", itinerary), ("summarize", summarize),
    ]:
        g.add_node(name, fn)

    g.add_edge(START, "clarify")
    g.add_conditional_edges("clarify", route_after_clarify,
                            {"clarify": "clarify", "dispatch": "dispatch"})
    for n in ("weather", "attractions", "restaurants", "transport"):
        g.add_edge("dispatch", n)
        g.add_edge(n, "itinerary")
    g.add_edge("itinerary", "summarize")
    g.add_edge("summarize", END)
    return g.compile(checkpointer=MemorySaver())
```

- [ ] **Step 4: 移除被取代的 M1 流式测试**

图从此变为 M2(clarify 首节点会调真实 LLM)，旧的 `tests/test_chat_stream.py::test_chat_stream_emits_token_and_final`（针对 M1 dispatch→summarize 单轮）已不适用——其完整流式覆盖由 Task 11 的 `test_chat_stream_m2.py` 接管。删除该测试函数，**保留** `test_health` 与 `test_chat_rejects_empty_message`（这两条不跑图：health 是存活探针，空消息在 pydantic 校验阶段即 422，图不执行；二者仅需 fail-fast 假 Key，fixture 已具备）。其 `client` fixture 与对 `summarize.build_llm` 的打桩若仅服务于被删测试，可一并清理。

- [ ] **Step 5: 运行测试至全绿**

Run: `cd backend && uv run pytest -q`
Expected: 全部 PASS（含 test_builder、各节点单测、test_contracts、保留的 health/422）；输出 pristine。

- [ ] **Step 6: Commit**

```bash
cd backend && git add app/graph/builder.py tests/test_builder.py tests/test_chat_stream.py
git commit -m "feat(m2): builder 接线完整 M2 图 + MemorySaver；移除被取代的 M1 流式测试"
```

---

### Task 11: 桥接层 `stream.py` 升级 + `chat.py`(session/clarify/resume/token 过滤) + 端到端测试

**Files:**
- Modify: `backend/app/graph/stream.py`
- Modify: `backend/app/api/chat.py`
- Modify: `backend/tests/test_chat_stream.py`(M1 测试随契约更新)
- Create: `backend/tests/test_chat_stream_m2.py`
- Create: `backend/tests/test_clarify_interrupt.py`

**Interfaces:**
- Produces:
  - `async def sse_events(message, thread_id, request)`：新会话 yield `session` + 以 `{"query":...,"messages":[],"clarified":False,"clarify_round":0}` 启图；非空 thread_id 有 pending interrupt → `Command(resume=message)`，否则以新 query 启图。流中按 NODES 发 `node_start`(+label)/`node_end`，按 `langgraph_node=="summarize"` 发 `token`。流后 `aget_state` 判 pending：有则发 `clarify`(interrupt.value)，否则发 `final`(`{"answer":summary,"day_plans":day_plans}`)。异常发脱敏 `error`。
  - `chat` 端点透传 `req.thread_id`。
- Consumes: 全部探针实测取值(见 Global Constraints 🔬 条目)。

- [ ] **Step 1: 写端到端测试**

> 打桩策略(关键)：**不重建 GRAPH**，也**不**替换整个节点函数(builder 已绑定原函数引用，替换模块属性无效)。而是 patch 各节点模块内**运行时解析**的 `build_llm` / `_evaluate_gaps`——节点函数体在调用时按模块全局名解析这些符号，patch 即生效(M1 测试已验证此法)。`client` fixture(conftest)负责假 Key 绕过 fail-fast。

`tests/test_chat_stream_m2.py`(齐备需求 → 直达 final，token 只来自 summarize)：
```python
import re


def _stub_nodes(monkeypatch):
    """clarify 无缺口放行、dispatch/itinerary 给结构化、summarize 流式。检索由 fake_amap 提供。"""
    from app.graph.nodes import clarify as c, dispatch as d, itinerary as it, summarize as s
    from app.graph.nodes.dispatch import NormalizedReq
    from app.graph.nodes.itinerary import DayPlans, DayPlan, PlanItem, Location, DayWeather
    from tests.conftest import make_fake_build_llm

    async def no_gaps(_state):
        return []
    monkeypatch.setattr(c, "_evaluate_gaps", no_gaps)
    monkeypatch.setattr(d, "build_llm", make_fake_build_llm(
        structured=NormalizedReq(city="成都", days=1, num_people=2,
                                 preferences={"food": "辣"}, budget=2000.0)))
    monkeypatch.setattr(it, "build_llm", make_fake_build_llm(structured=DayPlans(days=[
        DayPlan(day=1, weather=DayWeather(), center=Location(lng=104.0, lat=30.6),
                items=[PlanItem(type="attraction", name="武侯祠", poi_id="B1",
                                location=Location(lng=104.0, lat=30.6))])])))
    monkeypatch.setattr(s, "build_llm", make_fake_build_llm(tokens=["第一天", "：武侯祠"]))


def test_full_stream_reaches_final_with_day_plans(client, fake_amap, monkeypatch):
    fake_amap["search_poi"] = [{"name": "武侯祠", "poi_id": "B1", "lng": 104.0,
                                "lat": 30.6, "address": "", "type": ""}]
    _stub_nodes(monkeypatch)
    body = client.post("/api/chat", json={"message": "成都玩1天"}).text
    assert "event: session" in body
    assert "event: final" in body
    assert "event: token" in body
    assert "武侯祠" in body            # day_plans 进了 final
    # token 只来自 summarize：正文出现攻略 token，但不含中间节点产物
    assert "第一天" in body
```

`tests/test_clarify_interrupt.py`(模糊输入 → session+clarify；同 thread resume → final)：
```python
import json
import re


def _stub_except_clarify(monkeypatch):
    """保留真实 clarify（触发 interrupt）：_evaluate_gaps 按 clarify_history 变化；其余节点打桩。"""
    from app.graph.nodes import clarify as c, dispatch as d, itinerary as it, summarize as s
    from app.graph.nodes.clarify import Gap
    from app.graph.nodes.dispatch import NormalizedReq
    from app.graph.nodes.itinerary import DayPlans, DayPlan, PlanItem, Location, DayWeather
    from tests.conftest import make_fake_build_llm

    async def eval_gaps(state):
        if state.get("clarify_history"):
            return []  # 已答 → 放行
        return [Gap(field="city", question="去哪个城市？", options=["成都", "北京"])]
    monkeypatch.setattr(c, "_evaluate_gaps", eval_gaps)
    monkeypatch.setattr(d, "build_llm", make_fake_build_llm(
        structured=NormalizedReq(city="成都", days=1)))
    monkeypatch.setattr(it, "build_llm", make_fake_build_llm(structured=DayPlans(days=[
        DayPlan(day=1, center=Location(lng=104.0, lat=30.6),
                items=[PlanItem(type="attraction", name="武侯祠")])])))
    monkeypatch.setattr(s, "build_llm", make_fake_build_llm(tokens=["第一天", "：武侯祠"]))


def test_clarify_then_resume_to_final(client, fake_amap, monkeypatch):
    _stub_except_clarify(monkeypatch)
    first = client.post("/api/chat", json={"message": "我想出去玩"}).text
    assert "event: session" in first
    assert "event: clarify" in first
    tid = re.search(r'"thread_id":\s*"([0-9a-f]+)"', first).group(1)

    second = client.post("/api/chat", json={"message": "成都", "thread_id": tid}).text
    assert "event: final" in second
    assert "武侯祠" in second
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_chat_stream_m2.py tests/test_clarify_interrupt.py -q`
Expected: FAIL(stream.py 尚未支持 session/clarify/resume)。

- [ ] **Step 3: 实现 `app/graph/stream.py`**

```python
"""桥接层（M2）：astream_events(v2) → SSE。区分暂停(clarify)与完成(final)。
🔬 探针实测：interrupt 暂停时流干净结束；流后 aget_state().tasks[].interrupts[0].value 取澄清 payload；
token 仅放行 metadata.langgraph_node=="summarize"。
"""
import json
import uuid

from langgraph.types import Command

from app.core.constants import (
    EVENT_SESSION, EVENT_NODE_START, EVENT_TOKEN, EVENT_NODE_END,
    EVENT_CLARIFY, EVENT_FINAL, EVENT_ERROR, NODES, NODE_LABELS,
)
from app.graph.builder import build_graph

GRAPH = build_graph()


def _sse(event: str, payload: dict) -> dict:
    return {"event": event, "data": json.dumps(payload, ensure_ascii=False)}


async def sse_events(message: str, thread_id: str | None, request):
    new_session = thread_id is None
    if new_session:
        thread_id = uuid.uuid4().hex  # ⚠️ 运行期生成
    config = {"configurable": {"thread_id": thread_id}}
    try:
        if new_session:
            yield _sse(EVENT_SESSION, {"thread_id": thread_id})
            stream_input = {"query": message, "messages": [],
                            "clarified": False, "clarify_round": 0}
        else:
            snap = await GRAPH.aget_state(config)
            pending = any(t.interrupts for t in snap.tasks) if snap and snap.tasks else False
            stream_input = Command(resume=message) if pending else {"query": message}

        async for ev in GRAPH.astream_events(stream_input, config=config, version="v2"):
            if await request.is_disconnected():
                break
            kind, name = ev["event"], ev.get("name")
            if kind == "on_chain_start" and name in NODES:
                yield _sse(EVENT_NODE_START, {"node": name, "label": NODE_LABELS.get(name, "")})
            elif kind == "on_chat_model_stream" and ev.get("metadata", {}).get("langgraph_node") == "summarize":
                tok = ev["data"]["chunk"].content
                if tok:
                    yield _sse(EVENT_TOKEN, {"text": tok})
            elif kind == "on_chain_end" and name in NODES:
                yield _sse(EVENT_NODE_END, {"node": name})

        # 流后判定：暂停等澄清 or 编排完成
        snap = await GRAPH.aget_state(config)
        interrupts = [t.interrupts[0] for t in (snap.tasks or []) if t.interrupts]
        if interrupts:
            yield _sse(EVENT_CLARIFY, interrupts[0].value)
        else:
            answer = (snap.values or {}).get("summary", "")
            day_plans = (snap.values or {}).get("day_plans", [])
            yield _sse(EVENT_FINAL, {"answer": answer, "day_plans": day_plans})
    except Exception:  # noqa: BLE001 —— 脱敏
        yield _sse(EVENT_ERROR, {"message": "生成失败，请重试"})
```

- [ ] **Step 4: 实现 `app/api/chat.py`(透传 thread_id)**

```python
from fastapi import APIRouter, Request
from sse_starlette import EventSourceResponse

from app.schemas.chat import ChatRequest
from app.graph.stream import sse_events

router = APIRouter()


@router.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    return EventSourceResponse(sse_events(req.message, req.thread_id, request), ping=15)
```

- [ ] **Step 5: 确认 `tests/test_chat_stream.py` 现状**

无需再改动 M1 测试：AMAP 假 Key 已在 Task 2 补入其 fixture，被取代的旧流式测试已在 Task 10 移除（仅留 health/422）。本步只需在 Step 6 全量套件中确认它们仍绿。新 M2 端到端覆盖由本任务的 `test_chat_stream_m2.py` 与 `test_clarify_interrupt.py` 提供。

- [ ] **Step 6: 运行全部后端测试至全绿**

Run: `cd backend && uv run pytest -q`
Expected: 全部 PASS，输出 pristine(无多余 warning)。

- [ ] **Step 7: Commit**

```bash
cd backend && git add app/graph/stream.py app/api/chat.py tests/test_chat_stream_m2.py tests/test_clarify_interrupt.py
git commit -m "feat(m2): 桥接层支持 session/clarify/resume/token 过滤 + 端到端测试"
```

---

### Task 12: 前端契约与状态(types / sse.ts / store)

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/sse.ts`
- Modify: `frontend/src/stores/trip.ts`

**Interfaces:**
- Produces:
  - `types`: `EventName` 加 `'session'|'clarify'`；新增 `SessionPayload{thread_id}`、`ClarifyPayload{field,question,options}`；`NodeStartPayload` 加可选 `label?:string`；`FinalPayload` 加 `day_plans?: any[]`。
  - `sse.ts`: `fetchChatStream(message, threadId, onChunk, signal)`——请求体 `{message, thread_id}`。
  - `store`: `threadId:ref<string|null>`、`dayPlans:ref<any[]>`、`clarifyPending:ref<ClarifyPayload|null>`、`agentProgress: ref<Record<string,'running'|'done'>>`；actions `setThreadId/setClarify/clearClarify/setDayPlans/startNode/endNode/clearProgress`。

- [ ] **Step 1: 改 `src/types/index.ts`**

```ts
export interface NodeStartPayload { node: string; label?: string }
export interface TokenPayload { text: string }
export interface NodeEndPayload { node: string }
export interface FinalPayload { answer: string; day_plans?: any[] }
export interface ErrorPayload { message: string }
export interface SessionPayload { thread_id: string }
export interface ClarifyPayload { field: string; question: string; options: string[] }

export type EventName =
  | 'session' | 'node_start' | 'token' | 'node_end' | 'clarify' | 'final' | 'error';
```

- [ ] **Step 2: 改 `src/api/sse.ts`(请求体带 thread_id)**

把函数签名与 body 改为：
```ts
export async function fetchChatStream(
  message: string,
  threadId: string | null,
  onChunk: (event: string, data: any) => void,
  signal?: AbortSignal
) {
  const baseUrl = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
  const response = await fetch(`${baseUrl}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, thread_id: threadId }),
    signal
  })
  // …以下解析逻辑保持不变…
```
(其余 ReadableStream 解析逻辑不变。)

- [ ] **Step 3: 改 `src/stores/trip.ts`**

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ClarifyPayload } from '../types'

export interface Message {
  role: 'user' | 'assistant'
  content: string
  kind?: 'text' | 'clarify'   // clarify 问题气泡区别于普通文本
}

export const useTripStore = defineStore('trip', () => {
  const messages = ref<Message[]>([])
  const agentProgress = ref<Record<string, 'running' | 'done'>>({})
  const nodeLabels = ref<Record<string, string>>({})   // node_start 携带的后端友好文案
  const threadId = ref<string | null>(null)
  const dayPlans = ref<any[]>([])
  const clarifyPending = ref<ClarifyPayload | null>(null)

  const addMessage = (role: 'user' | 'assistant', content: string, kind: 'text' | 'clarify' = 'text') => {
    messages.value.push({ role, content, kind })
  }
  const appendToLastMessage = (text: string) => {
    const last = messages.value[messages.value.length - 1]
    if (!last || last.role !== 'assistant' || last.kind === 'clarify') {
      addMessage('assistant', text)
    } else {
      last.content += text
    }
  }
  const startNode = (node: string, label?: string) => {
    agentProgress.value[node] = 'running'
    if (label) nodeLabels.value[node] = label
  }
  const endNode = (node: string) => { agentProgress.value[node] = 'done' }
  const clearProgress = () => { agentProgress.value = {}; nodeLabels.value = {} }

  const setThreadId = (id: string) => { threadId.value = id }
  const setClarify = (c: ClarifyPayload) => {
    clarifyPending.value = c
    addMessage('assistant', c.question, 'clarify')
  }
  const clearClarify = () => { clarifyPending.value = null }
  const setDayPlans = (plans: any[]) => { dayPlans.value = plans }

  return {
    messages, agentProgress, nodeLabels, threadId, dayPlans, clarifyPending,
    addMessage, appendToLastMessage, startNode, endNode, clearProgress,
    setThreadId, setClarify, clearClarify, setDayPlans,
  }
})
```

- [ ] **Step 4: 验证类型编译**

Run: `cd frontend && bunx vue-tsc --noEmit`
Expected: 无类型错误(若机器无 bun，用 `npx vue-tsc --noEmit`)。

- [ ] **Step 5: Commit**

```bash
cd frontend && git add src/types/index.ts src/api/sse.ts src/stores/trip.ts
git commit -m "feat(m2): 前端契约与状态（thread_id/dayPlans/clarifyPending/进度 map）"
```

---

### Task 13: 前端行为与组件(useSSE / ClarifyOptions / MessageList / AgentProgress)

**Files:**
- Modify: `frontend/src/composables/useSSE.ts`
- Create: `frontend/src/components/ClarifyOptions.vue`
- Modify: `frontend/src/components/MessageList.vue`
- Modify: `frontend/src/components/AgentProgress.vue`
- Modify: `frontend/src/components/ChatPanel.vue`(挂载 ClarifyOptions)

**Interfaces:**
- Consumes: Task 12 的 store 与 types。
- Produces: `useSSE().send(message)` 带 `store.threadId`；处理 `session`(存 threadId)、`clarify`(停 loading + `setClarify`)、`final`(停 loading + `setDayPlans`)、`node_start/end`(更新 progress)、`token`(累加)、`error`。`ClarifyOptions.vue` 渲染当前 `clarifyPending` 的选项/自由输入 → 调 `send(answer)` 恢复。

- [ ] **Step 1: 改 `src/composables/useSSE.ts`**

```ts
import { ref } from 'vue'
import { fetchChatStream } from '../api/sse'
import { useTripStore } from '../stores/trip'
import { ElMessage } from 'element-plus'
import type {
  EventName, NodeStartPayload, TokenPayload, NodeEndPayload,
  ErrorPayload, SessionPayload, ClarifyPayload, FinalPayload,
} from '../types'

export function useSSE() {
  const loading = ref(false)
  const tripStore = useTripStore()
  let abortController: AbortController | null = null

  const send = async (message: string) => {
    if (!message.trim()) return
    loading.value = true
    tripStore.addMessage('user', message)
    tripStore.clearClarify()
    tripStore.clearProgress()
    abortController = new AbortController()

    try {
      await fetchChatStream(message, tripStore.threadId, (eventStr, data) => {
        switch (eventStr as EventName) {
          case 'session':
            tripStore.setThreadId((data as SessionPayload).thread_id)
            break
          case 'node_start': {
            const p = data as NodeStartPayload
            tripStore.startNode(p.node, p.label)
            break
          }
          case 'node_end':
            tripStore.endNode((data as NodeEndPayload).node)
            break
          case 'token':
            tripStore.appendToLastMessage((data as TokenPayload).text)
            break
          case 'clarify':
            tripStore.setClarify(data as ClarifyPayload)
            loading.value = false
            break
          case 'final':
            tripStore.setDayPlans((data as FinalPayload).day_plans || [])
            loading.value = false
            break
          case 'error':
            ElMessage.error((data as ErrorPayload).message || '生成失败')
            loading.value = false
            break
          default:
            console.warn('未知事件:', eventStr)
        }
      }, abortController.signal)
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        console.error('SSE 连接错误:', e)
        ElMessage.error('连接错误')
      }
    } finally {
      loading.value = false
    }
  }

  const abort = () => {
    if (abortController) { abortController.abort(); abortController = null; loading.value = false }
  }

  return { loading, send, abort }
}
```

- [ ] **Step 2: 新建 `src/components/ClarifyOptions.vue`**

```vue
<template>
  <div v-if="clarify" class="clarify-options">
    <el-radio-group v-if="clarify.options.length" v-model="picked" @change="onPick">
      <el-radio-button v-for="opt in clarify.options" :key="opt" :value="opt">{{ opt }}</el-radio-button>
    </el-radio-group>
    <div v-else class="free-input">
      <el-input v-model="freeText" placeholder="请输入…" @keyup.enter="onFree" />
      <el-button type="primary" @click="onFree">发送</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useTripStore } from '../stores/trip'

const props = defineProps<{ send: (msg: string) => void }>()
const tripStore = useTripStore()
const clarify = computed(() => tripStore.clarifyPending)
const picked = ref('')
const freeText = ref('')

const onPick = (val: string) => { props.send(val); picked.value = '' }
const onFree = () => { if (freeText.value.trim()) { props.send(freeText.value); freeText.value = '' } }
</script>

<style scoped>
.clarify-options { padding: 8px 16px; display: flex; gap: 8px; flex-wrap: wrap; }
.free-input { display: flex; gap: 8px; width: 100%; }
</style>
```

- [ ] **Step 3: 改 `src/components/MessageList.vue`(clarify 气泡区分)**

在消息渲染上对 `msg.kind === 'clarify'` 加不同样式类。最小改动：给 content 容器绑定 class：
```vue
      <div class="content" :class="{ 'clarify-bubble': msg.kind === 'clarify' }">
        <pre>{{ msg.content }}</pre>
      </div>
```
并在 `<style scoped>` 增：
```css
.content.clarify-bubble { background: #fdf6ec; border: 1px solid #f5dab1; color: #b88230; }
```

- [ ] **Step 4: 改 `src/components/AgentProgress.vue`(进度 map + label)**

```vue
<template>
  <div class="agent-progress">
    <div v-if="entries.length" class="progress-bar">
      <el-tag
        v-for="[node, status] in entries"
        :key="node"
        :type="status === 'done' ? 'success' : 'primary'"
        :effect="status === 'done' ? 'plain' : 'dark'"
        size="small"
        class="node-tag"
      >{{ labelOf(node) }}</el-tag>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useTripStore } from '../stores/trip'

const LABELS: Record<string, string> = {
  clarify: '理解需求', dispatch: '梳理要点', weather: '查询天气',
  attractions: '检索景点', restaurants: '挑选餐厅', transport: '规划交通',
  itinerary: '编排行程', summarize: '生成攻略',
}
const tripStore = useTripStore()
const entries = computed(() => Object.entries(tripStore.agentProgress))
// 优先展示后端 node_start 携带的 label，无则回退本地映射
const labelOf = (n: string) => tripStore.nodeLabels[n] || LABELS[n] || n
</script>

<style scoped>
.agent-progress { padding: 8px 0; min-height: 24px; }
.progress-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.node-tag { transition: all .3s; }
</style>
```

- [ ] **Step 5: 改 `src/components/ChatPanel.vue` 挂载 ClarifyOptions**

在 `<ChatInput .../>` 上方加 `<ClarifyOptions :send="send" />`，并 import：
```vue
import ClarifyOptions from './ClarifyOptions.vue'
```
模板：
```vue
    <ClarifyOptions :send="send" />
    <ChatInput :loading="loading" @send="send" @abort="abort" />
```

- [ ] **Step 6: 验证类型编译**

Run: `cd frontend && bunx vue-tsc --noEmit`
Expected: 无类型错误。

- [ ] **Step 7: Commit**

```bash
cd frontend && git add src/composables/useSSE.ts src/components/ClarifyOptions.vue src/components/MessageList.vue src/components/AgentProgress.vue src/components/ChatPanel.vue
git commit -m "feat(m2): 前端澄清选项气泡 + 多节点进度点亮 + final 存 day_plans"
```

---

### Task 14: `backend/README.md` M2 验收清单

**Files:**
- Modify: `backend/README.md`

**Interfaces:** 无代码接口；交付 M2 验收文档。

- [ ] **Step 1: 在 README 增 M2 验收章节**

加入(沿用设计文档 §9)：
- 配置：`.env` 填 `OPENAI_API_KEY`(或中转 `OPENAI_BASE_URL`) + `AMAP_WEB_KEY`。
- 起后端：`uv run uvicorn app.main:app --reload --port 8000`，`GET /health` ok。
- 澄清多轮 curl(首轮模糊输入收 `session`+`clarify`；复制 `thread_id` 二次请求作答恢复，齐备后逐条 token + 末尾 `final` 含 `day_plans`)：
  ```bash
  curl -N -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
    -d '{"message":"我想出去玩"}'
  curl -N -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
    -d '{"message":"成都，3天，2人，爱吃辣，预算人均2000","thread_id":"<上一步的id>"}'
  ```
- 端到端：`cd frontend && bun run dev`，模糊需求 → 澄清问题+选项 → 作答 → 进度点亮 → 逐字攻略。
- 测试：`cd backend && uv run pytest -q` 全绿(全打桩，不依赖真实 Key/网络)。

- [ ] **Step 2: Commit**

```bash
cd backend && git add README.md
git commit -m "docs(m2): backend README 增 M2 验收清单"
```

---

## 验收总览(全部任务完成后)

- `cd backend && uv run pytest -q` 全绿；输出 pristine。
- 真实 Key(OpenAI + 高德)下 curl 多轮澄清 → final 含 day_plans。
- 前端模糊需求 → 澄清气泡 + 选项 → 进度点亮 → 逐字攻略。
- `accommodation`/`budget` 仍占位，不在图上。
