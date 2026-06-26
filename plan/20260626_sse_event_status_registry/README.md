# SSE 事件状态管理台账

## 任务目标

集中管理 SSE 事件的“是否需要后端推送、前端是否展示、展示在哪里、是否只是控制状态”，避免内部控制流事件误展示到聊天框。

本次根据用户最新决策调整：

- 不再使用 `ask_user` 工具。
- 不再使用 `clarify` 专用 SSE 事件。
- 信息不足时，由系统提示词要求模型直接用普通 assistant 文本追问用户；前端通过 `token` 正常展示。

## 本次改动

### 1. 取消 `ask_user` 工具

原因：

- `ask_user` 本质是内部暂停工具，会产生 `tool_call` / `tool_result` pill。
- 这些 pill 对用户没有直接价值，还会和真正的问题气泡重复。

处理：

- 从后端工具定义中删除 `ask_user`。
- 从 Agent 工具列表 `_TOOLS` 中移除 `ask_user`。
- 从工具展示文案 `TOOL_LABELS` 中移除 `ask_user`。
- 系统提示词改为：信息不足时不要调用工具，不要编造，直接回复提问。

### 2. 取消 `clarify` 专用事件

原因：

- 不再用 `interrupt` 暂停图执行。
- 缺信息的追问就是普通 AI 回复，不需要单独事件、单独气泡、单独选项组件。

处理：

- 后端 `stream.py` 不再检测 `interrupts`，也不再发送 `EVENT_CLARIFY`。
- 后续同一会话输入始终作为普通 `HumanMessage` 继续进入 Agent。
- 前端移除 `ClarifyPayload`、`clarify` 事件分支、`clarifyPending` 状态和 `ClarifyOptions.vue`。
- `Message.kind` 只保留 `text` / `error`。

### 3. 保留待处理：`error` 需要进入聊天框

现象：

- 后端推送 `error`：
  - `{"message":"生成失败，请重试"}`
  - 或 `{"message":"会话不存在或已删除，请新建会话后重试"}`
- 前端当前只用 `ElMessage.error(...)` 做错误 toast。
- 聊天消息列表里没有留下错误内容。

期望：

- `error.message` 应该进入聊天框，作为 assistant 的错误消息展示。
- toast 可以保留，但不应该是唯一展示方式。

后续建议：

- 在 `frontend/src/composables/useSSE.ts` 的 `error` 分支调用 store 写入一条错误消息。
- 复用现有 `Message.kind = 'error'` 和 `MessageList.vue` 的错误样式。

### 4. 保留待处理：建立专门的 SSE 状态 registry

现状：

- 事件契约和展示策略仍分散在：
  - `backend/app/core/constants.py`
  - `backend/app/graph/stream.py`
  - `frontend/src/types/index.ts`
  - `frontend/src/composables/useSSE.ts`
  - `frontend/src/stores/trip.ts`
  - `frontend/src/components/MessageList.vue`

期望：

- 建立一份专门的 SSE 事件状态/展示策略管理位置。
- 每个事件至少明确：
  - 后端是否推送
  - 前端是否消费
  - 是否用户可见
  - 展示位置
  - 是否有起始/结束配对
  - 是否仅用于状态同步

后续建议：

- 后端保留事件名常量，集中管理工具展示文案、隐藏策略、节点标签。
- 前端建立事件处理 registry，避免 `useSSE.ts` 的 switch 越来越散。
- 文档层同步维护事件矩阵，作为前后端契约说明。

## 当前事件矩阵

| SSE 事件 | 后端是否推送 | 前端是否消费 | 用户是否可见 | 展示位置 / 用途 | 备注 |
|---|---:|---:|---:|---|---|
| `session` | 是 | 是 | 否 | 保存 `thread_id` | 控制状态 |
| `token` | 是 | 是 | 是 | 聊天正文 | 信息不足追问也走这里 |
| `tool_call` | 是 | 是 | 是 | 工具链 pill | 仅真实工具 |
| `tool_result` | 是 | 是 | 是 | 工具链完成态 | 仅真实工具 |
| `node_start` | 是 | 是 | 部分 | “正在思考...”临时提示 | 仅 running 时有意义 |
| `node_end` | 是 | 是 | 否 | 结束 running 状态 | 不单独展示 |
| `plan_patch` | 是 | 是 | 否 | 更新 `plan_version` | 目前只做状态 |
| `final` | 是 | 是 | 部分 | 收尾 + 写入行程/预算 | `answer` 当前不二次展示 |
| `title` | 是 | 是 | 是 | 会话列表标题 | 非聊天正文 |
| `error` | 是 | 是 | 是 | 应进入聊天框，可附带 toast | 待处理 |
| `intent` | 暂无实际推送 | 暂无处理 | 否 | 保留类型 | 待清理或补齐 |

已取消：

| 旧机制 | 处理 |
|---|---|
| `ask_user` 工具 | 删除 |
| `clarify` SSE 事件 | 删除 |
| `ClarifyOptions.vue` | 删除 |
| `clarifyPending` store 状态 | 删除 |

## 改动文件

### 后端

- `backend/app/agent/tools.py`
- `backend/app/agent/build.py`
- `backend/app/agent/prompt.py`
- `backend/app/core/constants.py`
- `backend/app/graph/stream.py`
- `backend/tests/agent/test_prompt.py`

### 前端

- `frontend/src/types/index.ts`
- `frontend/src/composables/useSSE.ts`
- `frontend/src/stores/trip.ts`
- `frontend/src/components/ChatPanel.vue`
- `frontend/src/components/MessageList.vue`
- `frontend/src/components/ClarifyOptions.vue`
- `frontend/components.d.ts`
- `frontend/tests/sse.test.ts`

## 待办

- [ ] 前端把 `error.message` 写入聊天消息列表。
- [ ] 设计并落地 SSE 事件展示/状态 registry。
- [ ] 清理历史 README 中旧的 `clarify interrupt` 描述。
- [ ] 视需要清理 `intent` 事件类型。

## 测试结果

- `cd backend && uv run pytest tests/agent/test_prompt.py tests/agent/test_stream_react.py -q`：4 passed。
- `cd frontend && bun test tests/sse.test.ts`：1 pass。
- `cd frontend && bun run build`：通过；构建输出包含 Rolldown 对 `@vueuse/core` pure annotation 的既有警告，以及 `src/App.vue` 动态/静态重复导入提示。
- `cd backend && uv run pytest -q`：51 passed，4 warnings。

## 相关讨论

- 用户明确指出：不需要在前端展示的内部状态，就不应该由后端推送到前端。
- 用户明确决定：`ask_user` 工具不要了，把缺信息追问写在系统提示词里。
- 用户明确决定：`clarify` 专用澄清事件也不要了。
- 用户明确指出：`error` 目前只作为 toast，不在聊天框展示，需要记录为待处理问题。
- 用户要求：写一个专门的地方来管理这些状态，并把这个需求本身也记录下来。
