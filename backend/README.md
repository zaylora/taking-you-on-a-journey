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

## 测试

```bash
uv run pytest        # 对 LLM 工厂打桩，不依赖真实 Key/网络
```

## 注意事项（落地实测要点）

- **.env 无 BOM**：Windows 下务必保存为 UTF-8（无 BOM），否则解析报错。
- **前端直连 + CORS**：前端不走 Vite proxy，直连本服务（`VITE_API_BASE=http://localhost:8000`）；后端已开 `CORSMiddleware` 放行 `cors_origins`（默认 `http://localhost:5173`）。跨域部署到不同域时按需调整环境变量 `CORS_ORIGINS`（JSON 数组）。
- **Python ≤3.10 流式坑**：`summarize` 节点必须 `async def` + 接收 `config` + `llm.astream(..., config=config)` 显式透传，否则 `on_chat_model_stream` 不冒泡、前端收不到逐字 token（已实测确认）。
- **版本实测**：langgraph 无 `__version__`，用 `importlib.metadata.version("langgraph")` 查版本。
