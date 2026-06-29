# 结构化澄清机制

## 任务目标

参考 `E:\github\hermes-agent` 的澄清机制，为当前旅行规划 App 增加结构化澄清能力：当 Agent 缺少城市、天数等关键条件时，通过 SSE 发出 `clarify` 事件，前端展示问题和选项，用户下一轮沿用同一会话继续。

## 改动文件清单

| 文件 | 说明 |
| --- | --- |
| `docs/superpowers/plans/2026-06-29-structured-clarification.md` | 本次实现计划 |
| `backend/app/core/constants.py` | 新增 `clarify` SSE 事件常量 |
| `backend/app/agent/state.py` | 增加 `clarification_request` 状态字段 |
| `backend/app/agent/tools/clarify.py` | 新增 `ask_clarification` 工具 |
| `backend/app/agent/tools/__init__.py` | 导出澄清工具 |
| `backend/app/agent/build.py` | 注册澄清工具到 ReAct Agent |
| `backend/app/agent/prompt.py` | 要求缺关键条件时调用澄清工具 |
| `backend/app/graph/stream.py` | 检测澄清状态并发出 `clarify`，本轮不发 `final` |
| `backend/app/services/tool_labels.py` | 为澄清工具生成中文进度文案 |
| `backend/tests/agent/test_tools.py` | 覆盖澄清工具 state 写入和选项规范化 |
| `backend/tests/test_chat_stream.py` | 覆盖 SSE 澄清事件和持久化行为 |
| `frontend/src/types/index.ts` | 新增 `ClarifyPayload` 和 `clarify` 事件名 |
| `frontend/src/stores/trip.ts` | 支持澄清消息数据 |
| `frontend/src/composables/useSSE.ts` | 处理 `clarify` 事件 |
| `frontend/src/components/MessageList.vue` | 渲染澄清选项按钮 |
| `frontend/src/components/ChatPanel.vue` | 选项点击后复用 `send()` 继续对话 |

## 改动详情

- 采用短连接澄清协议，不照搬 Hermes 的阻塞等待模型。原因是当前项目基于 `/api/chat` SSE 请求和 `thread_id` 持久会话，发出澄清后结束本轮更符合浏览器连接模型。
- `ask_clarification` 只做结构化写 state：`field`、`question`、最多 4 个 `options`。它不等待用户回答，也不新增独立响应 API。
- `sse_events` 在 graph 执行后读取 `clarification_request`；若存在问题文本，则发出 `clarify` 事件、持久化 user 与 assistant 问句，并直接结束本轮，不发送 `final`。
- 前端收到 `clarify` 后把问题显示为 assistant 消息，选项作为按钮渲染。点击选项走现有 `send()`，继续使用当前会话。

## 测试结果

- `cd backend && uv run pytest tests/agent/test_tools.py::test_ask_clarification_writes_structured_request tests/agent/test_tools.py::test_ask_clarification_trims_options_to_four_and_drops_blank_values -q`：通过。
- `cd backend && uv run pytest tests/test_chat_stream.py::test_sse_events_emits_clarify_and_stops_without_final tests/test_chat_stream.py::test_sse_events_ignores_stale_clarification_when_current_run_did_not_ask -q`：通过。
- `cd backend && uv run pytest -q`：通过，132 passed。
- `cd frontend && bun run build`：通过；仍有既有第三方 Rolldown/VueUse pure annotation 警告。

## 相关讨论

- Hermes 的价值主要在产品形态：结构化问题、选项、自由输入和取消/超时语义。本次只实现当前项目最需要的结构化问题与选项，不做超时和独立响应接口。
- 当前没有新增配置项或抽象层，后续若需要多平台澄清或长期挂起，再考虑引入 request id 与 pending 状态表。
