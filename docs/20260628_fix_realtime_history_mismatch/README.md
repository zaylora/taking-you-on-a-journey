# 修复实时生成与历史记录展示不一致

## 任务目标

排查并修复旅行攻略生成时，实时聊天气泡与历史回放内容不一致的问题：历史中用户首问可能消失、工具调用数量变少、小红书来源链接缺失。

## 改动文件

- `backend/app/services/session_store.py`
- `backend/app/services/message_history.py`
- `backend/app/graph/stream.py`
- `backend/app/api/sessions.py`
- `backend/tests/test_chat_stream.py`
- `backend/tests/test_session_aggregate.py`
- `backend/tests/test_sessions.py`

## 改动详情

- 根因：历史接口直接从 LangGraph checkpoint 的 `messages` 聚合 UI 消息，但这些 `messages` 是模型上下文，不是 UI 历史。长生成中 `ContextEditingMiddleware` / `SummarizationMiddleware` 会清理或改写旧消息；同时实时流的工具步骤来自 SSE `tool_call/tool_result` 事件，小红书来源来自 stream 层追加 token，二者不一定存在于最终 `AIMessage.content/tool_calls` 里。
- 新增 `session_messages` 表，专门持久化“前端可回放消息”：用户输入、assistant 正文、错误状态和工具步骤。
- `sse_events` 在实时生成时同步累计 token 与工具步骤，结束后写入 `session_messages`，保证历史回放使用的内容与实时气泡一致。
- 旧会话兼容：如果某个会话还没有 `session_messages`，下一次生成前会先用现有 graph checkpoint 聚合并 seed 一次旧历史，避免新逻辑隐藏旧内容。
- 旧会话历史回放：历史接口在没有 `session_messages` 时，会遍历 LangGraph checkpoint history，而不是只读最新 state；从早期 snapshot 恢复用户首问和最长工具调用链，从最新 snapshot 取最终正文，避免上下文压缩后历史只剩 assistant 和少量工具。
- 历史接口 `/api/sessions/{thread_id}` 优先读取 `session_messages`；没有 UI 历史时才回退到 graph messages。
- 小红书来源渲染与消息聚合抽到 `app/services/message_history.py`，避免 stream 和 sessions 各维护一套逻辑。
- 错误路径也持久化 user + assistant error，避免实时看到错误气泡但历史里没有这一轮。

## 测试结果

- `uv run pytest tests/test_chat_stream.py tests/test_session_aggregate.py tests/test_sessions.py -q`：19 passed
- `uv run pytest tests/agent/test_stream_react.py tests/agent/test_build_agent.py tests/agent/test_state.py tests/agent/test_reducers.py -q`：11 passed
- `uv run pytest -q`：123 passed
- `bun test tests/sse.test.ts`：2 passed
- `bun run vue-tsc -b`：通过

## 相关讨论

- 没有改前端渲染，因为接口快照已能复现缺用户消息、缺来源、工具链与实时不同的问题。
- 将 UI 历史和模型上下文分离后，后续上下文压缩策略可以继续服务模型成本控制，不再影响用户可见历史。
