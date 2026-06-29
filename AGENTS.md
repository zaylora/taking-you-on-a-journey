# AGENTS.md

对话式 AI 旅游规划 App。后端 FastAPI + LangGraph（ReAct agent），前端 Vue 3 + Vite。

## 技术栈

- **后端**：Python ≥3.12 · [uv](https://docs.astral.sh/uv/) 管理依赖 · FastAPI · LangGraph 1.2.5（`create_agent` ReAct）· langchain-openai / langchain-anthropic · SSE（sse-starlette）· pydantic-settings · SQLite checkpointer · pytest（`asyncio_mode=auto`）。
- **前端**：Vue 3（`<script setup>`）· Vite · bun · TypeScript · Pinia · Vue Router · Element Plus · 高德 JS API。
- **外部服务**：OpenAI/Anthropic（LLM）· 高德 Web 服务（后端代理）· 小红书 CLI（攻略检索）。

## 目录结构

```
backend/app/
  agent/        # ReAct agent：state、prompt、reducers、tools/、itinerary/（编排算法）
  api/          # FastAPI 路由（chat、sessions）
  core/         # config（pydantic-settings）、constants
  graph/        # LangGraph builder + stream（SSE 事件生成）
  llm/          # LLM 工厂
  schemas/      # Pydantic 请求/响应模型
  services/     # 会话存储等
  utils/        # 高德等外部封装
backend/tests/  # pytest，结构镜像 app/
frontend/src/   # api/、components/、composables/、stores/、types/、router/
docs/superpowers/  # specs/（设计文档）、plans/（实现计划）
plan/           # 每次改动的记录文档（见下）
```

## 命令

```bash
# 后端
cd backend && uv sync                          # 装依赖
uv run dev
uv run pytest -q                               # 测试（对 LLM/高德打桩，不依赖真实 Key/网络）

# 前端
cd frontend && bun install
bun run dev
bun run build                                  # = vue-tsc -b && vite build，类型检查即测试，须全绿
```

## 依赖优先原则

实现任何功能时，按以下顺序决策：

1. **优先成熟开源依赖**：前端特效、算法、工具函数等，先搜是否有广泛使用的库。
2. **禁止盲目手写**：不得跳过调研直接手写，即使看起来"很简单"。
3. **手写为最后手段**：仅当确无合适方案 / 现有依赖过大或有安全风险 / 项目特殊约束（离线、许可证）时手写，并明确说明"未找到合适依赖，选择手写，原因：……"。

## 代码约定

**后端（Python）**

- 模块/函数写中文 docstring，说明意图与坑点，不写无意义注释。
- 所有 agent tool 用 `@tool` 装饰、`async def`，需要写回 state 时返回 `langgraph.types.Command(update={...})`，并在 update 里带一条 `ToolMessage`。
- state 字段在 `TripState`(`AgentState` 子类) 声明；同一 step 可能并发写的字段必须配 reducer（如 `xhs_sources` 用 `merge_xhs_sources`），避免并发写冲突。
- 配置统一走 `core/config.py` 的 `Settings`，`get_settings()` 带 `lru_cache`；密钥用 `SecretStr` 存、绝不打印明文。
- 纯计算（预算核算、路线优化、聚类、diff）放 `itinerary/`，写成无副作用纯函数，单独测。

**前端（Vue/TS）**

- 组件用 `<script setup lang="ts">`；状态集中在 Pinia store（`stores/trip.ts`），跨会话结构定义在那。
- 类型集中在 `types/`，`day_plans` 等数据契约强类型化，`poi_id` 为卡片↔地图联动主键。
- SSE/HTTP 调用封装在 `api/`、`composables/`，组件不直接拼请求。

## 安全约定

- **Key 不下发前端**：高德 `AMAP_WEB_KEY`（Web 服务）后端代理调用；前端只用独立的 `VITE_AMAP_JS_KEY`（JS API，配域名白名单），两者不可混用。
- `.env` 含密钥绝不入库；务必存为**无 BOM 的 UTF-8**（Windows 易踩坑）。
- SSE `error` 事件须脱敏，不含 Key/堆栈。
- 中间节点的 LLM token 不暴露给前端，仅最终回复逐字流出。

## 测试约定

- 后端改动配 pytest，测试目录镜像 `app/`；对 LLM 工厂与高德 tool 打桩，不依赖真实 Key/网络。
- 纯函数（预算/路线/聚类/reducer）必须有针对性单测覆盖边界。
- 前端以 `bun run build`（`vue-tsc` 类型检查）作为契约校验，须全绿。

## SSE 事件契约（前后端共享）

| event                     | data                              | 含义                          |
| ------------------------- | --------------------------------- | ----------------------------- |
| `session`                 | `{"thread_id":"<uuid>"}`          | 首次返回会话 id               |
| `node_start` / `node_end` | `{"node":"..."}`                  | 节点进出                      |
| `clarify`                 | `{"field","question","options"}`  | 缺口澄清（interrupt）         |
| `token`                   | `{"text":"..."}`                  | 最终回复逐字输出              |
| `final`                   | `{"answer","day_plans","budget"}` | **结束信号**（禁用 `[DONE]`） |
| `error`                   | `{"message":"..."}`               | 出错（脱敏）                  |

## 改动记录规则

每次完成任务或实现改动，**必须**在 `plan/` 下创建记录：

- 文件夹：`plan/YYYYMMDD_<任务简述>/`，例如 `plan/20260628_xhs_source_links/`。
- 内含 `README.md`，包含：**任务目标**、**改动文件清单**（建议用表格）、**改动详情**（改了什么、为何这样改）、**测试结果**、**相关讨论**（重要设计决策）。
