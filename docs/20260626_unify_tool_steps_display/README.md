# 工具调用展示：移除思考过程 + 实时与历史统一为单条消息内聚合

## 任务目标

前端调整工具调用过程的展示：

1. **不再展示思考过程**（reasoning_content / extended thinking），只展示调用的工具链。
2. **实时与历史展示形态一致**：此前实时把一次回答的所有工具挤在「一个临时气泡」里、且流结束后丢失；历史则把 ReAct 每轮 `AIMessage` 拆成多条 assistant 消息。两者不一致。
3. 统一为**单条消息内聚合**：一次回答 = 一条 assistant 消息，本轮所有工具调用按顺序聚合成工具链挂在该消息里，下方接最终回答正文。
4. 工具调用 pill **垂直排列**。

## 根因分析

- **实时丢失**：ReAct 事件顺序为 `tool_call → tool_result …（多轮）→ token`。`tool_call` 到达时，消息列表最后一条仍是 user 消息，`store.startToolCall` 里 `last.role === 'assistant'` 判断失败，工具步骤只进了全局 `toolSteps`，没挂到任何 assistant 消息。工具链靠 `MessageList` 底部依赖 `loading` 的临时气泡显示，流结束 `loading=false` 后气泡消失，最终 assistant 消息又没带 `toolSteps`，工具链当场丢失。
- **历史多条**：`sessions.py` 的 `_message_to_dict` 逐条转换 `AIMessage`，ReAct 中间轮往往只有 `tool_calls`、正文为空，渲染成多条空气泡。

## 改动文件

### 后端
- `backend/app/api/sessions.py`：删除 `_message_to_dict` 与 `_extract_thinking`，新增 `_aggregate_messages`（按 `HumanMessage` 分轮，把相邻 `AIMessage` 折叠：工具步骤累积、正文拼接）与 `_tool_steps` 辅助；`_snapshot` 改用聚合函数。
- `backend/app/graph/stream.py`：停止发送 `thinking` 事件（移除 reasoning_content / extended thinking 提取），删除无用的 `_as_thinking` 与 `EVENT_THINKING` 引用。
- `backend/app/core/constants.py`：移除无消费方的 `EVENT_THINKING` 常量。

### 前端
- `frontend/src/stores/trip.ts`：
  - `Message` 接口移除 `thinkingText`，移除 `thinkingText` ref、`appendThinking`、`clearProgress` 中的 thinking 清理及导出。
  - 新增 `ensureAssistantMessage()`：取最后一条可追加的 assistant 占位消息，没有则懒创建一条空 assistant 消息。
  - `startToolCall` / `appendToLastMessage` 改为基于 `ensureAssistantMessage`，保证工具链与正文始终挂在同一条消息上（修复实时丢失）。
- `frontend/src/components/AgentProgress.vue`：纯 props 驱动（不再 fallback 全局 ref），移除思考过程折叠 UI 与「正在思考」兜底，工具 pill 由横向 `flex-wrap` 改为 `flex-direction: column` 垂直排列。
- `frontend/src/components/MessageList.vue`：移除底部依赖 `loading` 的实时进度气泡，移除 `hasProgress`/`useTripStore`/`progress-bubble` 样式；`AgentProgress` 仅在 assistant 消息含 `toolSteps` 时渲染；正文为空时不渲染空 markdown 块。
- `frontend/src/composables/useSSE.ts`：移除 `thinking` 事件 case 与 `ThinkingPayload` 引用。
- `frontend/src/types/index.ts`：移除 `ThinkingPayload`、`SessionSnapshot.messages[].thinking_text`、`EventName` 中的 `thinking`。

### 测试
- `backend/tests/test_session_aggregate.py`（新增）：3 个用例覆盖多 AIMessage 折叠、HumanMessage 分轮、System/Tool 消息跳过。

## 测试结果

- 后端 `pytest tests/`：**47 passed**（含新增 3 个聚合测试）。
- 前端 `vue-tsc -b` 类型检查：**零报错通过**。

## 相关讨论

- 形态决策由用户确认：在「单条消息内聚合」与「多条消息拆分」间选择前者，UX 更干净、无空气泡。
- 思考过程在源头（stream.py）停发而非仅前端不消费，保持前后端 SSE 契约干净、省带宽。
- `_aggregate_messages` 以 `HumanMessage` 为分轮边界，与实时流 `ensureAssistantMessage` 的「user 消息后开启新 assistant 占位」语义对齐，确保两端形态一致。
