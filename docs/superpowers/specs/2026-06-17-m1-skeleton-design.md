# M1 骨架与链路打通 — 设计文档

> 对应《项目策划书》第八章 M1 里程碑。
> 目标：搭建后端 FastAPI + uv 工程、前端 Vite + Vue 3 + Element Plus 骨架，
> 跑通最简 LangGraph（dispatch → summarize 直连）+ SSE 流式链路。

- **文档版本**：v1.0
- **日期**：2026-06-17
- **范围**：M1（单轮、无状态、无持久化的流式链路打通）
- **验收标准**：用户输入一句话，前端能流式看到 AI 逐字回复。
- **方案选型**：方案 A —— 按策划书 7.1 全量铺设目录骨架，但仅 dispatch / summarize 接线进 M1 图。

---

## 一、范围与边界

### 1.1 M1 做什么

- 后端 FastAPI + uv 工程，提供 `POST /api/chat`（SSE 流式）与 `GET /health`。
- 最简 LangGraph 两节点图：`START → dispatch → summarize → END`。
- `summarize` 节点调用真实 LLM（默认 OpenAI，支持自定义 base_url）。
- 桥接层把 LangGraph 事件流翻译为 SSE 事件（node_start / token / node_end / final / error）。
- 前端 Vite + Vue 3 + Element Plus 单页对话界面，消费 SSE 并逐字渲染。

### 1.2 M1 明确不做（防 scope creep）

| 不做项 | 归属里程碑 |
| ------ | ---------- |
| checkpointer / thread_id / 多轮会话记忆 | M2 |
| `clarify` 需求澄清（interrupt） | M2 |
| 4 个并行检索 Agent、`itinerary` 编排 | M2 |
| 高德地图打点、POI 代理、卡片联动 | M3 |
| `accommodation` + `budget_check` 超支回退 | M4 |
| 局部重排、攻略导出、进度指示器打磨 | M5 |
| 用户系统、PostgreSQL/Redis、容器化 | M6 |

`compile()` **不传 checkpointer**，无 thread_id，每次请求独立、无状态。

### 1.3 完整骨架 + 占位策略（方案 A 关键约定）

- `graph/nodes/` 下按策划书全量创建 10 个节点文件，但**只有 `dispatch` / `summarize` 接线进 M1 图**（`add_edge`）。
- 其余 8 个占位节点：函数体 `return {}` + `# TODO(Mx): ...` 注释。
  - **禁止 `pass`**：节点返回 `None` 会让 LangGraph 状态合并报错。
  - **禁止 `raise NotImplementedError`**：避免误连边时炸验收。
  - 占位节点**只建文件、不 `add_edge`**，保证编译出的图永远可运行。
- `api/plan.py`、`api/map_proxy.py`、`tools/`、`composables/useAMap.ts`、`components/MapView.vue` 等同为占位，不进 M1 验收路径。

---

## 二、系统架构

```
┌─────────────────────────────────────────────────────────────┐
│ 浏览器 (bun: Vite + Vue 3 + Element Plus + Pinia)            │
│   ChatInput → useSSE.send()                                  │
│   POST /api/chat  (fetch + ReadableStream 手动解析 SSE 帧)    │
│   按 event: 名分发 → Pinia store → MessageList 逐字渲染       │
└───────────────────────────┬─────────────────────────────────┘
                            │ 前端直连后端 :8000（VITE_API_BASE，需后端开 CORS）
                            │ 后端开 CORS 放行前端源（POST JSON 触发预检 OPTIONS）
┌───────────────────────────▼─────────────────────────────────┐
│ FastAPI (:8000)                                              │
│   POST /api/chat  →  graph/stream.py 桥接层                   │
│   GET  /health    →  {"status":"ok"} 存活探针                 │
└───────────────────────────┬─────────────────────────────────┘
                            │ astream_events(version="v2")
┌───────────────────────────▼─────────────────────────────────┐
│ LangGraph: START → dispatch → summarize → END                │
│   dispatch:  query 塞入 messages                              │
│   summarize: 调用 llm/factory.build_llm() → OpenAI            │
└───────────────────────────┬─────────────────────────────────┘
                            │ init_chat_model(model_provider="openai", base_url=...)
┌───────────────────────────▼─────────────────────────────────┐
│ LLM 工厂 (llm/factory.py)  默认 OpenAI，两家 SDK 都装          │
│   配置来自 core/config.py (pydantic-settings, SecretStr)      │
└──────────────────────────────────────────────────────────────┘
```

---

## 三、SSE 事件契约（前后端共享，最关键）

> ⚠️ 研究发现的硬冲突：后端示例用 `final` 结束，前端示例用 `[DONE]` 哨兵判停 —— 直接对接前端永远收不到结束。**M1 统一固化如下，禁用 `[DONE]`。**

| event | data（JSON 单行） | 含义 |
| ----- | ----------------- | ---- |
| `node_start` | `{"node":"dispatch"}` | 进入节点 |
| `token` | `{"text":"成"}` | LLM 逐字输出 |
| `node_end` | `{"node":"summarize"}` | 节点结束 |
| `final` | `{"answer":"完整回答文本"}` | **结束信号**（前端据此停止） |
| `error` | `{"message":"用户可读的错误"}` | 出错（脱敏，不含 Key/堆栈） |

**约定**：

- 所有 `data` 一律 `json.dumps(..., ensure_ascii=False)` 序列化为**单行**（data 字段不能含裸换行）。
- 前端**按 `event:` 名分发**（switch），**不靠拼 data 累加**：`token` 累加进正文，`final` 触发结束，`error` 提示并停 loading。
- 前后端各维护一份事件名常量，避免拼写漂移（后端 `core/constants.py` 或 chat.py 顶部常量；前端 `types/index.ts`）。
- 忽略以 `:` 开头的 SSE 注释/心跳行。

---

## 四、后端设计（FastAPI + uv）

### 4.1 目录结构

```
backend/
├── pyproject.toml          # uv 依赖声明，requires-python = ">=3.10"
├── uv.lock                 # 锁定版本
├── .env.example            # 仅键名/占位，提交入库
├── .gitignore              # 含 .env
├── README.md               # 启动与验收清单
├── app/
│   ├── __init__.py
│   ├── main.py             # ★ FastAPI 入口；注册路由；启动期 fail-fast 校验
│   ├── api/
│   │   ├── __init__.py
│   │   ├── chat.py         # ★ POST /api/chat（SSE）
│   │   ├── plan.py         # 占位：/api/plan/refine（M5）
│   │   └── map_proxy.py    # 占位：高德代理（M3）
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── state.py        # ★ TripState（M1 精简，预留全字段注释）
│   │   ├── builder.py      # ★ StateGraph：START→dispatch→summarize→END
│   │   ├── stream.py       # ★ 桥接层：astream_events → SSE dict 事件
│   │   └── nodes/
│   │       ├── __init__.py
│   │       ├── dispatch.py      # ★ 真实现
│   │       ├── summarize.py     # ★ 真实现（调 LLM 工厂）
│   │       ├── clarify.py       # 占位 return {} + TODO(M2)
│   │       ├── weather.py       # 占位 (M2)
│   │       ├── attractions.py   # 占位 (M2)
│   │       ├── restaurants.py   # 占位 (M2)
│   │       ├── transport.py     # 占位 (M2)
│   │       ├── itinerary.py     # 占位 (M2)
│   │       ├── accommodation.py # 占位 (M4)
│   │       └── budget.py        # 占位 (M4)
│   ├── llm/
│   │   ├── __init__.py
│   │   └── factory.py      # ★ build_llm()：init_chat_model，默认 OpenAI
│   ├── tools/
│   │   └── __init__.py     # 占位（高德/搜索，M2+）
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── chat.py         # ★ ChatRequest(message: str)
│   └── core/
│       ├── __init__.py
│       └── config.py       # ★ Settings（pydantic-settings，SecretStr 存 Key）
└── tests/
    ├── __init__.py
    └── test_chat_stream.py # ★ 流式单测（TestClient，LLM 打桩）
```

### 4.2 依赖与版本（经查证，落地前实测确认）

`requires-python = ">=3.10"`（sse-starlette 3.4.4 / langchain-core 1.x 的硬下限）。

```bash
uv init backend
cd backend
uv add "langgraph==1.2.5" langchain "langchain-openai==1.3.2" "langchain-anthropic==1.4.6" \
       "fastapi==0.137.1" "uvicorn[standard]==0.49.0" "sse-starlette==3.4.4" \
       "pydantic-settings==2.14.1" httpx
uv add --dev pytest
```

| 包 | 版本 | 说明 |
| --- | --- | --- |
| langgraph | 1.2.5 | **避开被 yank 的 1.2.3**；核心图原语跨 0.2→1.2 一致 |
| langchain-openai | 1.3.2 | ChatOpenAI；依赖 openai SDK 2.x |
| langchain-anthropic | 1.4.6 | ChatAnthropic（两家都装，工厂默认 OpenAI） |
| langchain-core | 随依赖解析 1.4.x | 提供 astream_events、AIMessageChunk |
| fastapi | 0.137.1 | — |
| uvicorn[standard] | 0.49.0 | Windows 无 uvloop，自动回退 asyncio |
| sse-starlette | 3.4.4 | EventSourceResponse / ServerSentEvent |
| pydantic-settings | 2.14.1 | BaseSettings + SecretStr |

> ⚠️ LangChain 生态已进 1.x（openai SDK 2.x / anthropic SDK 0.96+），勿照搬 0.x 教程版本号。
> ⚠️ 落地前先 `python -c "import langgraph; print(langgraph.__version__)"` 确认版本，并跑一次 astream_events 打印原始 chunk 形状再取值。

### 4.3 TripState（M1 精简版）

```python
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages

class TripState(TypedDict):
    # —— M1 使用 ——
    query: str                              # 用户原始输入
    messages: Annotated[list, add_messages] # 消息累加（reducer 防覆盖）
    summary: str                            # summarize 输出文本
    # —— M2+ 预留字段（注释占位，不在 M1 路径上）——
    # city / start_date / preferences / weather / attractions / day_plans ...
```

`messages` **必须用 `add_messages` reducer**，否则多节点写 messages 会相互覆盖。

### 4.4 节点实现

```python
# nodes/dispatch.py —— 真实现（不调模型，保持同步）
def dispatch(state: TripState) -> dict:
    return {"messages": [{"role": "user", "content": state["query"]}]}

# nodes/summarize.py —— 真实现：async + 透传 config + astream，token 才会冒泡
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from app.llm.factory import build_llm

async def summarize(state: TripState, config: RunnableConfig) -> dict:
    parts: list[str] = []
    async for chunk in build_llm().astream(state["messages"], config=config):
        if chunk.content:
            parts.append(chunk.content)
    text = "".join(parts)
    return {"messages": [AIMessage(content=text)], "summary": text}

# nodes/clarify.py 等占位
def clarify(state: TripState) -> dict:
    return {}  # TODO(M2): 需求澄清 interrupt + checkpointer
```

> ⚠️ **实测修正（Python 3.10 + async）**：节点内 `.invoke()` **不会**冒泡 `on_chat_model_stream`（前端收不到逐字 token）。Python ≤3.10 的 async 环境下 `RunnableConfig` 不经 contextvars 自动传播，节点内对 LLM 的调用会 callback 断链。故 `summarize` 必须 `async def` + 接收 `config` + `llm.astream(..., config=config)` 显式透传；`dispatch` 不调模型可保持同步。已用 astream_events 探针实测确认（node_start/end 取 `ev["name"]`、token 取 `ev["data"]["chunk"].content` 均成立）。

### 4.5 图构建（builder.py）

```python
from langgraph.graph import StateGraph, START, END
from app.graph.state import TripState
from app.graph.nodes.dispatch import dispatch
from app.graph.nodes.summarize import summarize

def build_graph():
    g = StateGraph(TripState)
    g.add_node("dispatch", dispatch)
    g.add_node("summarize", summarize)
    g.add_edge(START, "dispatch")
    g.add_edge("dispatch", "summarize")
    g.add_edge("summarize", END)
    return g.compile()   # M1：不传 checkpointer
```

### 4.6 桥接层（stream.py）—— 研究的最大盲区，单独成层

用 `app.astream_events(state, version="v2")` 映射（比 stream_mode 更易拿干净的 node_start）：

```python
import json
from app.graph.builder import build_graph

GRAPH = build_graph()
NODES = {"dispatch", "summarize"}

def _sse(event: str, payload: dict) -> dict:
    return {"event": event, "data": json.dumps(payload, ensure_ascii=False)}

async def sse_events(query: str, request):
    state = {"query": query, "messages": [], "summary": ""}
    answer = ""
    try:
        async for ev in GRAPH.astream_events(state, version="v2"):
            if await request.is_disconnected():
                break
            kind = ev["event"]
            if kind == "on_chain_start" and ev["name"] in NODES:
                yield _sse("node_start", {"node": ev["name"]})
            elif kind == "on_chat_model_stream":
                tok = ev["data"]["chunk"].content
                if tok:
                    answer += tok
                    yield _sse("token", {"text": tok})
            elif kind == "on_chain_end" and ev["name"] in NODES:
                yield _sse("node_end", {"node": ev["name"]})
        yield _sse("final", {"answer": answer})
    except Exception:  # noqa: BLE001
        # 脱敏：不泄露 Key/堆栈
        yield _sse("error", {"message": "生成失败，请重试"})
```

### 4.7 chat 端点（chat.py）

```python
from fastapi import APIRouter, Request
from sse_starlette import EventSourceResponse
from app.schemas.chat import ChatRequest
from app.graph.stream import sse_events

router = APIRouter()

@router.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    return EventSourceResponse(sse_events(req.message, request), ping=15)
```

### 4.8 配置与安全（config.py）

```python
from functools import lru_cache
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    llm_provider: str = "openai"
    openai_api_key: SecretStr = SecretStr("")
    openai_base_url: str | None = None       # 读 OPENAI_BASE_URL（自定义中转）
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_base_url: str | None = None
    anthropic_model: str = "claude-haiku-4-5-20251001"
    temperature: float = 0.0
    # 前端直连需放行的源（开发期 Vite 默认 5173）；可用环境变量 CORS_ORIGINS（JSON 数组）覆盖
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- `main.py` 启动期 **fail-fast**：默认 provider 的 Key 为空时直接报错退出。
- `SecretStr` 存 Key，传给 SDK 时 `.get_secret_value()`；日志/SSE/错误**绝不打印明文**。
- `.env` 存**无 BOM 的 UTF-8**（Windows 易踩 BOM 解析坑）。
- 注意 `OPENAI_API_BASE` 环境变量优先级高于 `OPENAI_BASE_URL`，二选一别同设。

### 4.9 LLM 工厂（factory.py）

```python
from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from app.core.config import get_settings

def build_llm(provider: str | None = None, **overrides) -> BaseChatModel:
    s = get_settings()
    provider = provider or s.llm_provider
    if provider == "openai":
        return init_chat_model(
            model=overrides.pop("model", s.openai_model),
            model_provider="openai",
            api_key=s.openai_api_key.get_secret_value() or None,
            base_url=s.openai_base_url,
            temperature=s.temperature,
            **overrides,
        )
    if provider == "anthropic":
        return init_chat_model(
            model=overrides.pop("model", s.anthropic_model),
            model_provider="anthropic",
            api_key=s.anthropic_api_key.get_secret_value() or None,
            base_url=s.anthropic_base_url,
            temperature=s.temperature,
            **overrides,
        )
    raise ValueError(f"unsupported provider: {provider}")
```

> 不同 provider 的 kwargs 不通用，工厂按 provider 分支组装，不把 OpenAI 专属参数盲传给 Anthropic。

### 4.10 main.py（开 CORS，前端直连）

前端直连后端（不走 Vite proxy），因此后端**必须开 `CORSMiddleware`**，放行前端源（`settings.cors_origins`，开发期默认 `http://localhost:5173`）：

```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,   # M1 无 cookie 鉴权，故 origins 用具体值即可，不用 "*"
    allow_methods=["*"],
    allow_headers=["*"],
)
```

POST `application/json` 会触发预检 OPTIONS，由 `CORSMiddleware` 自动处理。注册 `chat`/`plan`/`map_proxy` 路由与 `GET /health`；启动事件里做 Key fail-fast 校验。

---

## 五、前端设计（Vite + Vue 3 + Element Plus，bun）

### 5.1 目录结构

```
frontend/
├── package.json
├── vite.config.ts          # 基础配置（前端直连后端，无需 proxy）
├── tsconfig.json
├── .env / .env.example     # ★ VITE_API_BASE=http://localhost:8000（M1 必填，直连后端）
├── index.html
└── src/
    ├── main.ts             # ★ 装配 Pinia + Router（Element Plus 按需自动引入）
    ├── App.vue             # ★ 单页布局
    ├── api/
    │   └── sse.ts          # ★ fetch + ReadableStream 解析 SSE 帧
    ├── composables/
    │   ├── useSSE.ts       # ★ send()/abort()，按 event 分发回调
    │   └── useAMap.ts      # 占位（M3）
    ├── stores/
    │   └── trip.ts         # ★ Pinia：messages + agentProgress（精简）
    ├── components/
    │   ├── ChatPanel.vue        # ★ 消息流 + 输入
    │   ├── MessageList.vue      # ★ 逐字渲染
    │   ├── AgentProgress.vue    # ★ 简版（node_start/end 点亮）
    │   ├── ChatInput.vue        # ★ 输入框
    │   ├── ResultPanel.vue      # 占位（M3）
    │   └── MapView.vue          # 占位（M3）
    └── types/
        └── index.ts        # ★ 与事件契约对齐的 TS 类型
```

### 5.2 初始化与依赖（经查证）

```bash
bun create vite frontend --template vue-ts
cd frontend
bun install
bun add element-plus pinia vue-router axios @amap/amap-jsapi-loader @element-plus/icons-vue
bun add -d unplugin-vue-components unplugin-auto-import
bun run dev
```

| 包 | 版本 | 说明 |
| --- | --- | --- |
| vite | 8.x | 要求 Node ^20.19 \|\| >=22.12（本机 Node 22.22 ✓） |
| vue | 3.5.x | — |
| pinia | 3.0.4 | **vue-router 5.1 强制要求 pinia3 + vue3.5** |
| vue-router | 5.1.0 | — |
| element-plus | 2.14.2 | 按需引入 |
| unplugin-vue-components / unplugin-auto-import | 32.1 / 21.0 | Element Plus 自动引入 |
| axios | 1.18.0 | — |
| @amap/amap-jsapi-loader | 1.0.1 | M3 才用，先装占位 |

> bun 形式不需要 npm 的 `--` 分隔符。bun 需 Win10 1809+；若 `bun` not found，把 `%USERPROFILE%\.bun\bin` 加入 PATH。

### 5.3 SSE 消费（POST → fetch + ReadableStream）

> 原生 `EventSource` 只支持 GET、无法带 body/自定义头 → POST `${VITE_API_BASE}/api/chat`（前端直连后端，地址取自 `import.meta.env.VITE_API_BASE`）**必须** 用 `fetch + response.body.getReader() + TextDecoder` 手动解析。M1 **不引** `@microsoft/fetch-event-source`（无鉴权/重连需求），配 `AbortController` 支持"停止生成"。

`useSSE.ts` 要点：
- `\n\n` 分帧，保留跨 chunk 的尾部 buffer。
- 逐行解析 `event:` 与 `data:`，忽略 `:` 开头心跳。
- 按 `event` 名分发：`token` → 累加正文；`node_start/node_end` → 更新 `agentProgress`；`final` → 结束；`error` → ElMessage 提示 + 停 loading。

### 5.4 前端直连后端（不使用 Vite proxy）

前端通过 `VITE_API_BASE` 直接请求后端 `http://localhost:8000`，**不配置 Vite proxy**。`vite.config.ts` 仅保留 Vue 与 Element Plus 自动引入插件，无 `server.proxy`：

```ts
// vite.config.ts —— 无 proxy，前端直连后端（跨域由后端 CORS 放行）
export default defineConfig({
  plugins: [
    vue(),
    AutoImport({ resolvers: [ElementPlusResolver()] }),
    Components({ resolvers: [ElementPlusResolver()] }),
  ],
})
```

> SSE 缓冲：直连后端时无中间代理层，uvicorn 不做 gzip，且 `sse-starlette` 默认带 `X-Accel-Buffering: no`，逐字 token 不会被缓冲。跨域预检与响应头由后端 `CORSMiddleware` 处理。

---

## 六、错误处理与边界情况

| 场景 | 处理 |
| ---- | ---- |
| 缺 OPENAI_API_KEY | 启动期 fail-fast，直接报错退出 |
| LLM 调用中途抛错 | 桥接层 try/except → `yield error` 事件（脱敏）→ 优雅收尾 |
| 客户端断开 | `request.is_disconnected()` 检测 + 处理 `CancelledError`，防任务泄漏 |
| 前端收到 error | switch 处理 → `loading=false` + ElMessage 提示 |
| SSE 被缓冲 | 前端直连后端、无代理层；sse-starlette 默认带 `X-Accel-Buffering:no`，uvicorn 不 gzip |
| 跨域预检 (CORS) | 后端 CORSMiddleware 放行 `cors_origins`；POST application/json 的 OPTIONS 预检自动处理 |
| .env BOM | 要求无 BOM UTF-8 |

---

## 七、验收（写进 backend/README.md）

1. **装依赖 + 配置**：`cd backend && uv sync && cp .env.example .env`，编辑填入 `OPENAI_API_KEY`（可选 `OPENAI_BASE_URL` 中转地址）。
2. **起后端**：`uv run uvicorn app.main:app --reload --port 8000`，访问 `GET /health` 返回 `{"status":"ok"}`。
3. **后端独立验流**（绕开前端）：
   ```bash
   curl -N -X POST http://localhost:8000/api/chat \
     -H "Content-Type: application/json" \
     -d '{"message":"帮我规划三天东京行程"}'
   ```
   `-N` 关闭 curl 缓冲，肉眼确认逐条 `event: token` 流出、末尾有 `event: final`。
4. **端到端**：`cd frontend && bun install && bun run dev`，浏览器输入一句话，确认正文**逐字出现** → ✅ 达成 M1 验收标准。

### 测试

- `tests/test_chat_stream.py`：FastAPI `TestClient` 调 `/api/chat`，**对 LLM 工厂打桩**（monkeypatch `build_llm` 返回假流式模型），断言响应中包含 `event: token` 与 `event: final`，不依赖真实 Key/网络。

---

## 八、风险与缓解

| 风险 | 缓解 |
| ---- | ---- |
| LangGraph 1.2 流式 API 转述未逐字核实 | 已实测：版本用 `importlib.metadata.version()`（langgraph 无 `__version__`）；astream_events v2 中 `on_chain_start/end` 的 `ev["name"]` 即节点名、`on_chat_model_stream` 的 `ev["data"]["chunk"].content` 即 token |
| Python 3.10 async 下节点内 invoke 不冒泡 token | 已实测确认：`summarize` 用 `async def` + 接收 `config` + `llm.astream(..., config=config)` 显式透传，token 方能冒泡（≤3.10 RunnableConfig 不经 contextvars 自动传播） |
| `[DONE]` vs `final` 结束信号冲突 | 本设计统一用 `final`，前端禁用 `[DONE]` 哨兵 |
| POST+SSE 前端易错 | 固定用 fetch+ReadableStream，给出解析要点清单 |
| 跨域配置 | 前端直连后端，后端开 CORSMiddleware 放行前端源；不用 Vite proxy，避免双层混乱 |
| 占位节点返回 None 报错 | 占位一律 `return {}`，且不接线进 M1 图 |
| Windows BOM / bun PATH | README 注明无 BOM、PATH 配置 |

---

## 九、交付物清单

- `backend/` 完整骨架（10 节点文件，2 个真实现 + 8 占位）+ `/api/chat` SSE + `/health`。
- `frontend/` 单页对话界面（消费 SSE 逐字渲染）。
- `backend/README.md` 含四步验收清单。
- `backend/tests/test_chat_stream.py` 流式单测。
- `.env.example`（前后端）+ `.gitignore`（含 `.env`）。
