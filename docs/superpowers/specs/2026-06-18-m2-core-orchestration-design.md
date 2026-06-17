# M2 核心 Agent 编排 — 设计文档

> 对应《项目策划书》第八章 M2 里程碑。
> 目标：在 M1 已打通的 SSE 流式骨架上，接线完整核心编排：
> `clarify`（interrupt 多轮澄清）→ `dispatch` → 4 个并行检索 Agent → `itinerary` 行程编排 → `summarize`。

- **文档版本**：v1.0
- **日期**：2026-06-18
- **范围**：M2（多轮澄清 + 真实高德检索 + 算法聚类分天 + 结构化逐日行程）
- **验收标准**：输入模糊需求时能多轮追问澄清（带选项、可恢复）；澄清完成后产出结构化 `day_plans`，并在对话区逐字流式输出逐日中文攻略。地图卡片联动留 M3。

---

## 〇、关键决策记录（本里程碑落地前已拍板）

| 决策点 | 选型 | 理由 |
| ------ | ---- | ---- |
| 4 个检索 Agent 数据源 | **真实高德 Web API**（已有 Key） | 最贴近最终形态；后端代理，Key 不下发前端 |
| `day_plans` 前端展示 | **文本攻略 + 状态存结构化数据** | summarize 渲染逐日中文攻略逐字流式；结构化 `day_plans` 存状态供 M3 地图消费，M2 不做卡片 UI |
| `itinerary` 聚类分天 | **手写贪心 + 预留 `cluster_by_day` 接口** | 10-30 个点量级，手写零依赖且能直接表达「每天均衡+顺路」业务约束；接口固定，未来到 numpy 生态拐点可替换为 KMeans 而不动节点/图 |
| 会话 `thread_id` 来源 | **后端生成**，`session` 事件首帧下发 | 前端无需预生成；后端用 uuid 作 checkpointer thread，interrupt 跨请求恢复 |
| checkpointer | **MemorySaver** | MVP 内存级；产品化（M6）换持久化后端 |

---

## 一、范围与边界

### 1.1 M2 做什么

- **接线 6 个真实节点进图**：`clarify` / `dispatch`（升级）/ `weather` / `attractions` / `restaurants` / `transport` / `itinerary` / `summarize`（升级）。
- **`clarify` 需求澄清**：`interrupt` + `MemorySaver` checkpointer + `thread_id`，跑通「评估缺口 → 提问（带选项）→ 暂停 → 用户作答 → 恢复 → 再评估」的多轮问答，齐备后放行。
- **4 个并行检索 Agent**：`dispatch` 后并行触发 `weather/attractions/restaurants/transport`，各调真实高德 API，写入 State 独立字段。
- **`itinerary` 行程编排**：手写贪心 `cluster_by_day` 聚类分天 + 顺路排序 → LLM structured output 填充每日描述/餐厅就近分配 → 产出结构化 `day_plans`。
- **`summarize` 升级**：从「直接复述用户输入」改为「按 `day_plans` 渲染逐日中文攻略」，逐字流式。
- **桥接层升级**：支持 interrupt 检测（发 `clarify` 而非 `final`）、resume、按 `langgraph_node` 过滤 token、首帧 `session`。
- **前端升级**：thread_id 会话态、clarify 选项渲染与恢复、多节点并行进度点亮、final 携带 `day_plans` 入状态。

### 1.2 M2 明确不做（防 scope creep）

| 不做项 | 归属里程碑 |
| ------ | ---------- |
| 高德地图打点、POI 卡片联动、地图点选反向改行程 | M3 |
| `day_plans` 的右侧卡片/时间线 UI | M3 |
| `accommodation` 住宿 Agent | M4 |
| `budget_check` 预算核算 + 超支回退条件边 | M4 |
| 局部重排（替换/删除单项）、攻略导出、进度指示器精细打磨 | M5 |
| 用户系统、PostgreSQL/Redis 持久化（checkpointer 换持久化后端）、容器化 | M6 |

`accommodation` / `budget` 两个节点 M2 **仍是占位**（`return {}`，不 `add_edge`）。

### 1.3 节点接线状态总览

| 节点 | M1 | M2 | 说明 |
| ---- | -- | -- | ---- |
| `clarify` | 占位 | **接线·真实现** | interrupt 多轮澄清 |
| `dispatch` | 真实现（塞 messages） | **升级** | 需求标准化 → `normalized_req` |
| `weather` | 占位 | **接线·真实现** | 高德天气 API |
| `attractions` | 占位 | **接线·真实现** | 高德 POI + LLM 筛选 |
| `restaurants` | 占位 | **接线·真实现** | 高德 POI |
| `transport` | 占位 | **接线·真实现** | 高德路径/搜索 |
| `itinerary` | 占位 | **接线·真实现** | 聚类分天 + LLM 填充 |
| `summarize` | 真实现（复述） | **升级** | 按 day_plans 渲染攻略 |
| `accommodation` | 占位 | 占位（不变） | M4 |
| `budget` | 占位 | 占位（不变） | M4 |

---

## 二、系统架构（M2 图结构）

```
START
  │
  ▼
clarify ──(clarified=False)──┐   条件边：缺口未补完则自循环继续追问
  │  ▲                       │   （每轮在 interrupt 处暂停，等用户作答恢复）
  │  └───────────────────────┘
  │(clarified=True)
  ▼
dispatch（需求标准化 → normalized_req）
  │
  ├──────────┬──────────┬──────────┐   并行：共享上游 dispatch，各写独立字段
  ▼          ▼          ▼          ▼
weather  attractions restaurants transport
  │          │          │          │
  └──────────┴────┬─────┴──────────┘   4 入边全到齐，LangGraph 自动汇聚
                  ▼
              itinerary（cluster_by_day 分天 → LLM 填充 → day_plans）
                  ▼
              summarize（按 day_plans 渲染逐日攻略，逐字流式）
                  ▼
                 END
```

`compile(checkpointer=MemorySaver())`。`accommodation` / `budget` 不在图上。

---

## 三、契约变更（前后端共享，最关键）

### 3.1 SSE 事件全集

沿用 M1 的 5 个事件，**新增 `session` 与 `clarify`**：

| event | data（JSON 单行） | 含义 | 新增/沿用 |
| ----- | ----------------- | ---- | --------- |
| `session` | `{"thread_id":"<uuid>"}` | **首帧**下发会话 id（仅新会话发一次） | 🆕 |
| `node_start` | `{"node":"attractions"}` | 进入节点（并行时会多个并发） | 沿用 |
| `token` | `{"text":"成"}` | LLM 逐字输出（**仅 summarize 节点**） | 沿用 |
| `node_end` | `{"node":"attractions"}` | 节点结束 | 沿用 |
| `clarify` | `{"field":"budget","question":"预算档位？","options":["经济","舒适","高端"]}` | 图在 interrupt 处暂停，抛澄清问题（**本轮结束信号之一**，options 空数组=自由文本） | 🆕 |
| `final` | `{"answer":"完整攻略文本","day_plans":[...]}` | 编排完成（**本轮结束信号之二**，扩展携带结构化数据） | 扩展 |
| `error` | `{"message":"用户可读错误"}` | 出错（脱敏） | 沿用 |

**两种「本轮结束」信号互斥**：`clarify` = 暂停等用户作答；`final` = 编排完成。前端收到任一都要停 loading；收到 `clarify` 额外渲染选项气泡。

### 3.2 `/api/chat` 请求体

```jsonc
{ "message": "string（必填，min_length=1）", "thread_id": "string | null（首次为 null）" }
```

后端分支（桥接层核心逻辑）：

| 入参 thread_id | 该 thread 状态 | 行为 |
| -------------- | -------------- | ---- |
| `null` | —— | 生成新 uuid，先 yield `session`，以 `{"query": message}` 启动图 |
| 非空 | 存在 pending interrupt | `Command(resume=message)` 恢复图 |
| 非空 | 无 pending interrupt | 在该 thread 上以新 query 启动（M2 主路径是 resume；该分支为多轮追加预留，行为最简：复用 thread 继续） |

### 3.3 前后端事件常量同步

后端 `app/core/constants.py` 增 `EVENT_SESSION = "session"`、`EVENT_CLARIFY = "clarify"`；前端 `types/index.ts` 的 `EventName` 同步加 `'session' | 'clarify'`。两边名字必须一致。

---

## 四、后端设计

### 4.1 依赖与配置变更

- **无新增 Python 依赖**（高德走 `httpx`，已在依赖里；聚类手写用标准库 `math`；MemorySaver 在 langgraph 内）。
- `core/config.py` 增 `amap_web_key: SecretStr = SecretStr("")`。
- `.env.example` 增：
  ```bash
  # === 高德 Web 服务（后端代理，Key 不下发前端）===
  AMAP_WEB_KEY=
  ```
- `main.py` 启动期 fail-fast 扩展：M2 需要高德 Key，启动时校验 `amap_web_key` 非空（与 LLM Key 一并校验）。

### 4.2 TripState 扩展

启用策划书 4.1 中 M2 所需字段（M4 字段 `hotels`/`budget_check`/`retry_count` 仍注释）：

```python
from typing import Annotated
from operator import add
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages

class TripState(TypedDict):
    # —— 沿用 ——
    query: str
    messages: Annotated[list, add_messages]
    summary: str

    # —— M2 启用 ——
    # 结构化需求（dispatch 标准化产出 + clarify 累积）
    city: str
    start_date: str
    days: int
    num_people: int
    preferences: dict          # {travel, food, ...}
    budget: float
    normalized_req: dict        # dispatch 整理后的结构化需求快照

    # 需求澄清
    clarify_history: Annotated[list, add]   # [{field, question, options, answer}]
    clarified: bool
    clarify_round: int          # 轮次计数，超上限兜底

    # 并行检索产出（各写独立字段，避免写冲突）
    weather: dict
    attractions: list           # [{name, poi_id, lng, lat, ...}]
    restaurants: list
    transport: dict

    # 行程编排产出
    daily_centers: list         # 每天活动中心点
    day_plans: list             # 逐日结构化行程（见 §六）

    # —— M4 预留（注释占位）——
    # hotels: list
    # budget_check: dict
    # retry_count: int
```

> 关键：并行节点写不同 key，无需 reducer；`clarify_history` 跨多轮自循环累加，用 `add` reducer 防覆盖。

### 4.3 高德 tool 层 `app/tools/amap.py`（新建）

后端代理高德 Web 服务，统一 `httpx.AsyncClient` + 超时 + 失败降级。Key 取自 `config.amap_web_key.get_secret_value()`，**绝不下发前端、绝不进日志/SSE**。

```python
# 函数签名（实现要点：async、超时 ~5s、异常降级返回兜底而非抛）
async def geocode(city: str) -> dict: ...
    # 城市 → 中心坐标 {lng, lat}。失败降级：返回 {} ，下游用城市名兜底

async def search_poi(city: str, keywords: str, poi_type: str = "", page_size: int = 20) -> list[dict]: ...
    # 景点/餐厅候选；每项含 name/poi_id/lng/lat/address/type
    # 失败/空：返回 []，由节点决定补搜或兜底

async def get_weather(city: str) -> dict: ...
    # 实时+预报；远期（超出预报范围）降级为季节气候文案
    # {text, temp, is_rainy, source: "forecast"|"climate"}

async def plan_route(origin: str, dest: str, mode: str = "transit") -> dict: ...
    # 大交通/市内交通方案；失败降级 {}
```

降级策略对应策划书风险表「高德 API 额度/限流 → 缓存 + 限流 + 失败降级」。M2 先做**失败降级 + 超时**；缓存/限流留后续优化（不阻塞验收）。

### 4.4 节点实现要点

**clarify（interrupt 多轮）**

```python
from langgraph.types import interrupt
# 1) LLM structured output 评估当前 state 的需求完整度，找缺口 gaps:[{field,question,options?}]
# 2) clarify_round 超上限（如 >=4）→ 取默认值兜底，return {"clarified": True}
# 3) 无缺口 → return {"clarified": True}
# 4) 有缺口 → answer = interrupt({"field":..., "question":..., "options":...})
#    （interrupt 传入的 dict 即 §3.1 clarify 事件的 data，桥接层原样下发，字段须与契约一致）
#    恢复后把 answer 解析进对应结构化字段 + 追加 clarify_history，return {"clarified": False, "clarify_round": +1, ...}
#    条件边 route_after_clarify 再次进入 clarify 评估下一缺口
```

- 条件边：`route_after_clarify(state) -> "dispatch" if state["clarified"] else "clarify"`。
- 最大轮次兜底：避免无限追问（策划书要求 ≤4 轮）。
- 「需求已完整」时首轮即 `clarified=True`，直接放行 → 退化为 M1 式单轮，无澄清气泡。

**dispatch（升级为需求标准化）**

- 把 clarify 阶段累积的字段 + 原始 query，用 LLM structured output 整理成 `normalized_req`（城市/日期/天数/人数/偏好/预算），并回填顶层结构化字段。不再只是塞 messages。

**4 个并行检索节点**

- 各 `async def` + 接收 `config`（与 summarize 同理，保证 callback 不断链）。
- `weather`：`get_weather(city)` → 写 `weather`。
- `attractions`：`search_poi(city, 偏好关键词, "风景名胜")` → LLM 按偏好筛选/排序 → 写 `attractions`。补搜上限 ≤3 轮、最少候选阈值。
- `restaurants`：`search_poi(city, 饮食偏好, "餐饮")` → 写 `restaurants`。
- `transport`：`plan_route(...)` → 写 `transport`。
- 单节点失败不抛、走降级，不阻断其余并行节点；`itinerary` 用已有数据降级排程。

**itinerary（聚类分天 + LLM 填充）**

```python
# app/graph/nodes/itinerary.py
def cluster_by_day(points: list[dict], days: int) -> list[list[dict]]:
    """手写贪心：城市中心 → 按方位/距离分 days 簇（每天均衡）→ 簇内最近邻顺路排序。
    纯函数、零依赖（仅 math），单测友好。接口固定：未来可替换为 KMeans 而不动调用方。
    """
    ...

async def itinerary(state, config) -> dict:
    clusters = cluster_by_day(state["attractions"], state["days"])
    # 雨天（weather.is_rainy）将室外项替换为候选室内项
    # LLM structured output：按 clusters + restaurants + transport + weather
    #   填充每日时间线/描述/餐厅就近分配 → day_plans（schema 见 §六）
    return {"daily_centers": [...], "day_plans": [...]}
```

**summarize（升级）**

- 输入从 `messages` 改为 `day_plans`：system prompt 显式要求**简体中文**，按天渲染攻略文本。
- 保持 M1 实测结论：`async def` + 接收 `config` + `llm.astream(..., config=config)` 显式透传，token 方能逐字冒泡。

### 4.5 图构建 `builder.py`（升级）

```python
from langgraph.checkpoint.memory import MemorySaver
# ... import 8 个真实节点

def build_graph():
    g = StateGraph(TripState)
    for name, fn in [("clarify",clarify),("dispatch",dispatch),("weather",weather),
                     ("attractions",attractions),("restaurants",restaurants),
                     ("transport",transport),("itinerary",itinerary),("summarize",summarize)]:
        g.add_node(name, fn)
    g.add_edge(START, "clarify")
    g.add_conditional_edges("clarify", route_after_clarify,
                            {"clarify": "clarify", "dispatch": "dispatch"})
    for n in ("weather","attractions","restaurants","transport"):
        g.add_edge("dispatch", n)
        g.add_edge(n, "itinerary")
    g.add_edge("itinerary", "summarize")
    g.add_edge("summarize", END)
    return g.compile(checkpointer=MemorySaver())   # M2：带 checkpointer
```

### 4.6 桥接层 `stream.py`（升级，M2 最大盲区）

三个 M2 新增的硬骨头，落地前**必须探针实测**：

1. **token 污染过滤**：M1 只有 summarize 调 LLM，token 都是答案。M2 中 clarify/dispatch/检索/itinerary 都可能调 LLM，它们的 `on_chat_model_stream` 也会冒泡。**必须按 `ev["metadata"]["langgraph_node"]` 只放行 summarize 的 token**，否则中间推理 token 会污染正文。

2. **interrupt 检测**：图在 interrupt 处暂停时不会自然走到 END。astream_events 迭代结束后，查 `state = await GRAPH.aget_state(config)`；若 `state.tasks` 中存在 `interrupts`，取其 `.value`（即 `interrupt(...)` 传入的 dict）→ 发 `clarify` 事件，**不发 final**。否则（跑到 END）发 `final`（带 `day_plans`）。

3. **resume**：续轮用 `GRAPH.astream_events(Command(resume=message), config, version="v2")`。

```python
import json, uuid
from langgraph.types import Command
from app.graph.builder import build_graph
from app.core.constants import (EVENT_SESSION, EVENT_NODE_START, EVENT_TOKEN,
                                 EVENT_NODE_END, EVENT_CLARIFY, EVENT_FINAL, EVENT_ERROR)

GRAPH = build_graph()
NODES = {"clarify","dispatch","weather","attractions","restaurants","transport","itinerary","summarize"}

def _sse(event, payload): return {"event": event, "data": json.dumps(payload, ensure_ascii=False)}

async def sse_events(message: str, thread_id: str | None, request):
    new_session = thread_id is None
    if new_session:
        thread_id = uuid.uuid4().hex          # ⚠️ uuid4 需运行期生成，不可在模块顶层
    config = {"configurable": {"thread_id": thread_id}}
    try:
        if new_session:
            yield _sse(EVENT_SESSION, {"thread_id": thread_id})
            stream_input = {"query": message, "messages": [], "clarified": False, "clarify_round": 0}
        else:
            snap = await GRAPH.aget_state(config)
            pending = any(t.interrupts for t in snap.tasks) if snap and snap.tasks else False
            stream_input = Command(resume=message) if pending else {"query": message}

        async for ev in GRAPH.astream_events(stream_input, config=config, version="v2"):
            if await request.is_disconnected():
                break
            kind, name = ev["event"], ev.get("name")
            if kind == "on_chain_start" and name in NODES:
                yield _sse(EVENT_NODE_START, {"node": name})
            elif kind == "on_chat_model_stream" and ev["metadata"].get("langgraph_node") == "summarize":
                tok = ev["data"]["chunk"].content
                if tok: yield _sse(EVENT_TOKEN, {"text": tok})
            elif kind == "on_chain_end" and name in NODES:
                yield _sse(EVENT_NODE_END, {"node": name})

        # 迭代结束：区分「暂停等澄清」与「编排完成」
        snap = await GRAPH.aget_state(config)
        interrupts = [t.interrupts[0] for t in (snap.tasks or []) if t.interrupts]
        if interrupts:
            yield _sse(EVENT_CLARIFY, interrupts[0].value)      # {field, question, options}
        else:
            answer = (snap.values or {}).get("summary", "")
            day_plans = (snap.values or {}).get("day_plans", [])
            yield _sse(EVENT_FINAL, {"answer": answer, "day_plans": day_plans})
    except Exception:  # noqa: BLE001 —— 脱敏
        yield _sse(EVENT_ERROR, {"message": "生成失败，请重试"})
```

> ⚠️ 上述 `aget_state`/`tasks[].interrupts`/`metadata["langgraph_node"]` 的精确取值，落地前先用一段探针脚本对 langgraph 1.2.5 实测确认形状（与 M1 对 astream_events 的做法一致），再据实微调字段路径。

### 4.7 chat 端点 `chat.py`（升级）

```python
@router.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    return EventSourceResponse(sse_events(req.message, req.thread_id, request), ping=15)
```

`schemas/chat.py` 的 `ChatRequest` 增 `thread_id: str | None = None`。

---

## 五、前端设计

| 文件 | 变更 |
| ---- | ---- |
| `types/index.ts` | `EventName` 加 `'session'\|'clarify'`；加 `SessionPayload{thread_id}`、`ClarifyPayload{field,question,options}`；`FinalPayload` 加 `day_plans` |
| `api/sse.ts` | 请求体加 `thread_id`；新增参数透传 |
| `stores/trip.ts` | 加 `threadId`、`dayPlans`、`clarifyPending`（当前待答澄清问题）；`agentProgress` 改为 `Record<string,'running'\|'done'>` 真正点亮；加 `setThreadId/setClarify/clearClarify/setDayPlans` |
| `composables/useSSE.ts` | `send(message)` 带 store 的 `threadId`；处理 `session`（存 threadId）、`clarify`（停 loading + 渲染问题气泡 + 选项）、`final`（停 loading + 存 day_plans）；`node_start/end` 更新 progress map |
| `components/ClarifyOptions.vue`（新建） | 渲染 `el-radio-group`/`el-button` 选项；点选或自由输入 → 调 `send(answer)`（带同一 threadId）恢复 |
| `components/AgentProgress.vue` | 8 节点进度点亮（并行节点可同时 running） |
| `components/MessageList.vue` | 支持渲染 clarify 问题气泡（区别于普通 AI 文本） |

**多轮澄清前端时序**：

```
用户输入 → send(msg, threadId=null)
  ← session{thread_id}        前端存 threadId
  ← clarify{question,options} 前端停 loading，渲染问题+选项气泡
用户点选/输入 → send(answer, threadId)   后端 Command(resume) 恢复
  ← clarify{...}              （还有缺口，继续）
  ...（齐备后）
  ← node_start/token/node_end ... → final{answer, day_plans}
                              前端逐字渲染攻略，day_plans 存状态（供 M3）
```

---

## 六、`day_plans` 数据结构（itinerary 产出 / final 下发 / M3 消费）

```jsonc
[
  {
    "day": 1,
    "date": "2026-07-01",
    "weather": {"text": "多云", "temp": "24~31℃", "is_rainy": false},
    "center": {"lng": 104.06, "lat": 30.65},
    "items": [
      {"type": "attraction", "name": "武侯祠", "poi_id": "B001",
       "location": {"lng": 104.04, "lat": 30.64},
       "start": "09:00", "end": "11:00", "indoor": false, "note": "三国文化..."},
      {"type": "meal", "name": "陈麻婆豆腐", "poi_id": "B002",
       "location": {"lng": 104.05, "lat": 30.66}, "start": "12:00", "end": "13:00"},
      {"type": "transport", "mode": "地铁", "from": "武侯祠", "to": "...", "note": "..."}
    ]
  }
]
```

> M2 不含 `budget`/`hotel` 字段（M4 补）；`location` 字段为 M3 地图打点预留。结构与策划书 6.1 `final_plan.days` 对齐（M2 是其子集）。

---

## 七、错误处理与边界

| 场景 | 处理 |
| ---- | ---- |
| 缺 `AMAP_WEB_KEY` | 启动期 fail-fast 报错退出 |
| 高德超时/限流/空结果 | tool 层超时 + 异常降级（天气降季节气候、检索返回空给兜底文案），不抛断链路 |
| 单个并行节点失败 | 走降级写空/兜底字段，不阻断其余；itinerary 用已有数据降级排程 |
| clarify 无限追问 | `clarify_round` 上限（≤4），超限取默认值兜底放行 |
| 中间节点 LLM token 污染正文 | 桥接层按 `langgraph_node == "summarize"` 过滤 token |
| interrupt 未被识别成 clarify | 桥接层 `aget_state` 查 `tasks[].interrupts`，有则发 clarify 不发 final |
| 客户端断开 | 沿用 M1：`is_disconnected()` + CancelledError 收尾 |
| 前端收到 error | switch 处理 → 停 loading + ElMessage 提示 |

---

## 八、测试

- `test_clarify_interrupt.py`：打桩 LLM（构造「需追问→齐备」两轮缺口），TestClient 跑 `/api/chat`：首次响应含 `event: session` 与 `event: clarify`；带 thread_id 二次请求（resume）后续到 `final`。验证 interrupt/resume 跨请求恢复。
- `test_parallel_retrieval.py`：打桩 `amap.*` 四个函数，断言 4 节点各写入对应字段、单节点失败不阻断其余。
- `test_cluster_by_day.py`：**纯函数单测**——给定坐标列表与天数，断言分天数量均衡、簇内顺路（最近邻）合理、边界（点数 < 天数、单点）不崩。
- `test_itinerary.py`：打桩 LLM structured output，断言产出 `day_plans` 结构符合 §六 schema。
- `test_chat_stream_m2.py`（端到端，全打桩）：断言完整流含 `session`→（可选 clarify）→`node_start/token/node_end`→`final` 且 `final.day_plans` 非空；token 只来自 summarize。

所有测试**对 LLM 与高德 tool 打桩**，不依赖真实 Key/网络。

---

## 九、验收（写进 `backend/README.md`）

1. **配置**：`.env` 填 `OPENAI_API_KEY`（或中转 `OPENAI_BASE_URL`）+ `AMAP_WEB_KEY`。
2. **起后端**：`uv run uvicorn app.main:app --reload --port 8000`，`GET /health` 返回 ok。
3. **后端验澄清多轮**（curl，手动续 thread_id）：
   ```bash
   # 首轮：模糊输入 → 期望收到 session + clarify
   curl -N -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
     -d '{"message":"我想出去玩"}'
   # 复制返回的 thread_id，带上作答恢复
   curl -N -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
     -d '{"message":"成都，3天，2人，爱吃辣，预算人均2000","thread_id":"<上一步的id>"}'
   # 齐备后期望逐条 token 流出 + 末尾 final（含 day_plans）
   ```
4. **端到端**：`bun run dev`，输入模糊需求 → 对话区出现澄清问题 + 选项按钮 → 点选/作答 → 看到 Agent 进度点亮 → 逐字攻略 → ✅ 达成 M2 验收标准。

---

## 十、风险与缓解

| 风险 | 缓解 |
| ---- | ---- |
| interrupt 在 astream_events v2 下的冒泡/检测形态未逐字核实 | 落地前探针实测 `aget_state().tasks[].interrupts` 与 metadata；优先用「流后查 state」判定，不依赖事件流里的 interrupt 帧 |
| 中间节点 LLM token 污染正文 | 桥接层按 `langgraph_node == "summarize"` 过滤；中间节点一律 structured output（非流式） |
| 并行节点写 State 冲突 | 各写独立字段，不写同一 key（沿用策划书原则） |
| 高德 API 额度/限流/空结果 | tool 层超时 + 降级；M2 不做缓存（留后续，不阻塞验收） |
| 聚类质量（手写贪心） | 数据量级小（10-30 点）质量足够；`cluster_by_day` 接口固定，未来可换 KMeans |
| MemorySaver 重启丢会话 | MVP 接受；产品化（M6）换持久化 checkpointer |
| thread_id 透传断裂 | 后端首帧 `session` 下发，前端整会话固定带回；测试覆盖 resume 路径 |

---

## 十一、交付物清单

- `backend/app/tools/amap.py`（高德代理 tool 层，含降级）。
- 8 个真实节点（clarify/dispatch 升级 + weather/attractions/restaurants/transport/itinerary 新实现 + summarize 升级），`accommodation`/`budget` 保持占位。
- `builder.py` 接线完整 M2 图 + `MemorySaver`；`stream.py` 桥接层升级（session/clarify/resume/token 过滤）。
- `state.py` 扩展字段；`config.py`/`.env.example` 加 `AMAP_WEB_KEY`；`constants.py` 加 `session`/`clarify` 事件名。
- 前端：thread_id 会话态、`ClarifyOptions.vue`、进度点亮、final 携 day_plans 入状态。
- 5 个测试文件（全打桩，不依赖真实 Key/网络）。
- `backend/README.md` M2 验收清单更新。
