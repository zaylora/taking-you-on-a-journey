# 旅游规划 App · 后端（M1 骨架）

> 对话式 AI 旅游规划的最简流式链路：FastAPI + LangGraph（dispatch → summarize）+ SSE 逐字输出。
> 对应设计文档 `docs/superpowers/specs/2026-06-17-m1-skeleton-design.md`。

## 能力范围（M1）

- `POST /api/chat`：SSE 流式对话（单轮、无状态、无持久化）。
- `GET /health`：存活探针。
- LangGraph 两节点图：`START → dispatch → summarize → END`。
- 其余 8 个节点为占位（`return {}` + TODO），不接线进 M1 图，保证编译出的图永远可运行。

## 技术栈

Python ≥3.10 · uv · langgraph 1.2.5 · langchain-openai 1.3.2 · langchain-anthropic 1.4.6 ·
fastapi 0.137.1 · uvicorn 0.49.0 · sse-starlette 3.4.4 · pydantic-settings 2.14.1。

## 快速开始

```bash
cd backend
uv sync                       # 创建虚拟环境并按 uv.lock 安装依赖
cp .env.example .env          # PowerShell: Copy-Item .env.example .env
# 编辑 .env，至少填入 OPENAI_API_KEY（可选 OPENAI_BASE_URL 中转地址）
uv run uvicorn app.main:app --reload --port 8000
```

## 验收清单（四步）

1. **装依赖 + 配置**：`cd backend && uv sync && cp .env.example .env`，编辑填入 `OPENAI_API_KEY`（可选 `OPENAI_BASE_URL`）。
2. **起后端 + 健康检查**：`uv run uvicorn app.main:app --reload --port 8000`，访问 `GET http://localhost:8000/health` 返回 `{"status":"ok"}`。
3. **后端独立验流**（绕开前端；PowerShell 的 `curl` 是别名，请用 `curl.exe` 或 git bash）：
   ```bash
   curl.exe -N -X POST http://localhost:8000/api/chat \
     -H "Content-Type: application/json" \
     -d '{"message":"帮我规划三天东京行程"}'
   ```
   `-N` 关闭 curl 缓冲，肉眼确认逐条 `event: token` 流出，末尾有 `event: final`。
4. **端到端**：`cd frontend && bun install && bun run dev`，浏览器输入一句话，确认正文**逐字出现** → ✅ 达成 M1 验收标准。

## SSE 事件契约（前后端共享）

| event | data（JSON 单行） | 含义 |
| ----- | ----------------- | ---- |
| `node_start` | `{"node":"dispatch"}` | 进入节点 |
| `token` | `{"text":"成"}` | LLM 逐字输出 |
| `node_end` | `{"node":"summarize"}` | 节点结束 |
| `final` | `{"answer":"完整回答文本"}` | **结束信号**（前端据此停止；禁用 `[DONE]`） |
| `error` | `{"message":"用户可读的错误"}` | 出错（脱敏，不含 Key/堆栈） |

## M2 验收清单

M2 引入多轮澄清（interrupt）+ 真实高德检索 + 行程编排，核心能力：

- `POST /api/chat`：支持 `thread_id` 跨请求恢复；首次返回 `session`；缺口时返回 `clarify` 询问（可选项）；齐备后逐字流式行程，末尾 `final` 携 `day_plans` 结构化数据。
- `GET /health`：存活探针（M1 沿用）。
- 8 个节点接线图：`clarify` (interrupt) → `dispatch` → 4 并行检索（weather/attractions/restaurants/transport） → `itinerary` 分天聚类 → `summarize` 渲染行程 → END。
- `accommodation`/`budget` 仍占位（M4）。

### 配置与启动（M2）

```bash
cd backend
uv sync
cp .env.example .env                     # PowerShell: Copy-Item .env.example .env
# 编辑 .env，填入以下环境变量：
# OPENAI_API_KEY=sk-...（或中转 OPENAI_BASE_URL）
# AMAP_WEB_KEY=<高德 Web 服务 Key>（新增 M2 必需）

uv run uvicorn app.main:app --reload --port 8000
# 浏览器访问：GET http://localhost:8000/health → {"status":"ok"}
```

### 多轮澄清流验证（curl）

首轮：模糊输入 → 后端返回会话 id 与澄清问题。

```bash
curl -N -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
  -d '{"message":"我想出去玩"}'
```

**期望响应**（逐行，每行是一条 SSE 事件）：
- `event: session` → `data: {"thread_id":"<uuid>"}`（复制此 id）
- `event: node_start` → `data: {"node":"clarify","label":"正在理解你的需求…"}`
- `event: clarify` → `data: {"field":"city","question":"去哪座城市？","options":[...]}`（或其他缺口字段）

二轮：带 thread_id 作答 → 后端恢复图，继续评估或放行编排。

```bash
curl -N -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
  -d '{"message":"成都，3天，2人，爱吃辣，预算人均2000","thread_id":"<上一步的id>"}'
```

**期望响应**（缺口齐备后）：
- （可选）更多 `clarify`（若还有未回答的字段）
- `event: node_start` → dispatch/weather/attractions/... → summarize（4 个检索并行，各自 node_start/end）
- `event: token` → `data: {"text":"成都..."}` 逐字流出（仅 summarize 节点）
- `event: final` → `data: {"answer":"完整攻略...","day_plans":[...]}`（结束）

**说明**：PowerShell 的 `curl` 是别名，请用 `curl.exe` 或 git bash 确保 `-N` 参数被正确识别。

### 端到端验收（前端）

在 backend 已启动的前提下，新开终端：

```bash
cd frontend
bun install                    # 首次
bun run dev
# 浏览器访问 http://localhost:5173
```

**用户交互流程**：
1. 输入模糊需求，如"想在北京玩，时间不定"。
2. **澄清阶段**：对话区出现 AI 追问气泡（如"旅行时长？"）与选项按钮；点选或自由文本回答。
3. **进度可视化**：Agent 进度栏亮起（依次 clarify → dispatch → 并行检索 → itinerary → summarize）。
4. **结果呈现**：逐字渲染完整行程攻略（每天时间线、景点、餐厅、交通方案）；状态管理更新 `day_plans` 供 M3 地图消费。
5. **✅ 验收**：澄清、进度、逐字攻略三个环节顺利完成。

### 测试

```bash
cd backend
uv run pytest -q               # 对 LLM + 高德 tool 打桩，不依赖真实 Key/网络
# 期望：全绿（含 clarify interrupt、并行检索、聚类、end-to-end 流）
```

**关键测试覆盖**：
- `test_clarify_interrupt.py`：interrupt 与 resume 跨请求恢复。
- `test_parallel_retrieval.py`：4 并行节点各写独立字段，单节点失败不阻断其余。
- `test_cluster_by_day.py`：按天聚类逻辑（均衡分布、簇内顺路）。
- `test_itinerary.py`：行程编排产出 `day_plans` 符合结构。
- `test_chat_stream_m2.py`：完整 SSE 流 session → clarify → 并行 → final。

## 测试（M1）

```bash
uv run pytest        # 对 LLM 工厂打桩，不依赖真实 Key/网络
```

## 注意事项（落地实测要点）

- **.env 无 BOM**：Windows 下务必保存为 UTF-8（无 BOM），否则解析报错。
- **前端直连 + CORS**：前端不走 Vite proxy，直连本服务（`VITE_API_BASE=http://localhost:8000`）；后端已开 `CORSMiddleware` 放行 `cors_origins`（默认 `http://localhost:5173`）。跨域部署到不同域时按需调整环境变量 `CORS_ORIGINS`（JSON 数组）。
- **Python ≤3.10 流式坑**：`summarize` 节点必须 `async def` + 接收 `config` + `llm.astream(..., config=config)` 显式透传，否则 `on_chat_model_stream` 不冒泡、前端收不到逐字 token（已实测确认）。
- **版本实测**：langgraph 无 `__version__`，用 `importlib.metadata.version("langgraph")` 查版本。
- **M2 特别提示**：
  - 高德 Key 不下发前端，后端代理调用；Key 泄露将导致计费与安全隐患。
  - `clarify` 节点在无缺口时直接放行（退化为 M1 式单轮），有缺口时通过 `interrupt` 暂停，前端接 `clarify` 事件渲染问题 + 选项。
  - 中间节点（dispatch/weather/... 等）产生的 LLM token 不暴露给前端；仅 summarize 节点的 token 逐字流出。
  - 单个并行检索节点失败（如高德超时）走降级策略（返回空或季节气候），不阻断其余节点与后续编排。
