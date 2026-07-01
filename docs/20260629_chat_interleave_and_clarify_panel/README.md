# 聊天交错渲染 + 澄清浮层面板

日期：2026-06-29
分支：feature/交互
设计文档：`docs/superpowers/specs/2026-06-29-chat-interleave-and-clarify-panel-design.md`
实现计划：`docs/superpowers/plans/2026-06-29-chat-interleave-and-clarify-panel.md`

## 任务目标

两个需求：

1. **工具调用与 LLM 思维链交错呈现**（codex 风格）：把对话消息从「正文一坨 + 工具一坨」改为按到达顺序交错的「文本/工具」片段。中间推理淡色、输出时展开、写完自动折叠为「已思考」；最终回复黑色常展开。
2. **澄清浮层面板**：澄清从消息气泡内的选项按钮，改为输入框上方从下往上弹出的浮层，含选项按钮 + 自定义填写框；选择或提交后关闭、恢复输入框。

核心约束：**实时渲染与历史记录完全一致** —— 用统一的 segments 结构贯穿实时流、SQLite 持久化、graph 重建三条路径。

## 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `backend/app/services/message_history.py` | 修改 | 新增 `build_segments`/`segments_for_assistant`（`_tool_segments` 复用 `tool_steps`）；`messages_with_xhs_sources`/`reconstruct_messages_from_history`/`aggregate_messages` 产出 segments |
| `backend/app/services/session_store.py` | 修改 | `session_messages` 加 `segments` 列 + 幂等迁移；`append_ui_message`/`list_ui_messages` 读写 segments，旧行降级合成 |
| `backend/app/graph/stream.py` | 修改 | 流式按 token/tool 到达顺序维护 segments 并落库；澄清/笔记来源/error 分支同步 |
| `backend/app/api/sessions.py` | 未改 | 薄封装自动获得 message_history 的 segments 新行为 |
| `frontend/src/types/index.ts` | 修改 | 新增 `Segment` 类型；`SessionSnapshot.messages` 带 segments |
| `frontend/src/stores/trip.ts` | 修改 | `Message.segments` 取代 content+toolSteps；`appendToken`/`startToolCall`/`endToolCall` 改造；新增 `pendingClarify`/`setPendingClarify` |
| `frontend/src/composables/useSSE.ts` | 修改 | token 走 `appendToken`；clarify 设 `pendingClarify`；send 清 `pendingClarify` |
| `frontend/src/components/MessageList.vue` | 修改 | 按 segments 顺序渲染；reasoning 折叠；移除气泡内澄清选项 |
| `frontend/src/components/AgentProgress.vue` | 删除 | pill 样式内联进 MessageList，无引用后 git rm |
| `frontend/src/components/ClarifyPanel.vue` | 新增 | 澄清浮层（选项 + 自定义填写 + 关闭，从下往上弹出） |
| `frontend/src/components/ChatPanel.vue` | 修改 | `.input-area` 相对定位容器挂载 ClarifyPanel；移除残留 `@clarify-answer` |
| `AGENTS.md` | 修改 | 更新「中间节点 token 不暴露前端」安全约定为符合本次实现 |
| 测试 | 修改/新增 | `test_session_aggregate.py`/`test_sessions.py`/`test_chat_stream.py` 补 segments 覆盖 |

## 改动详情

### 数据契约（贯穿前后端）

- text 段：`{"kind":"text","text":...}`
- tool 段：`{"kind":"tool","tool":...,"label":...,"status":"running"|"done"}`（历史一律 done）
- **reasoning / answer 不存储**，渲染期判定：segments 中最后一个 text 段为 answer（黑色常展开），其余为 reasoning（淡色可折叠）。

### 后端三路径产出 segments

1. **实时流**（`stream.py`）：`on_chat_model_stream` 推 text 段（末尾是 text 则追加，否则新开）；`on_tool_start` 推 running tool 段并收尾前一个；`on_tool_end` 把对应 tool 段标 done；流末收尾残留 running；笔记来源追加到末尾 text 段。落库 `append_ui_message(..., segments=segments)`。
2. **SQLite 持久化**（`session_store.py`）：`session_messages` 加 `segments TEXT` 列（`PRAGMA table_info` 检查 + `ALTER TABLE ADD COLUMN` 幂等迁移）；旧行无 segments 时降级合成（tool 段在前 done、content 转 text 段在后）。
3. **graph 重建**（`message_history.py`）：`build_segments` 把一轮内 AIMessage 序列按出现顺序转交错段；`segments_for_assistant` 取末轮；`messages_with_xhs_sources` 把来源追加到末尾 text 段并同步 content。

### 前端渲染

- store `Message.segments` 取代 content+toolSteps；`appendToken` 累积文本段、`startToolCall`/`endToolCall` 维护 tool 段状态。
- `MessageList` 遍历 `displaySegments`（渲染期标 answer/reasoning）：tool 段渲染 pill；answer 段黑色 markdown 常展开；reasoning 段淡色，流式写入中展开、写完折叠为「已思考」，可点击切换。
- `ClarifyPanel` 经 store `pendingClarify` 显示，选项/自定义答案经 `useSSE().send` 发出后清空 pendingClarify。

## 测试结果

```
后端：cd backend && uv run pytest -q   →  140 passed
前端：cd frontend && bun run build      →  vue-tsc 零错误，vite build 成功
```

## 相关讨论（关键设计决策）

1. **实时与历史完全一致**：用户明确要求。初版设计只盯 graph checkpointer，遗漏了历史回放真正读取的 SQLite `session_messages` 表（落库时顺序信息丢失）。修正为 segments 贯穿三路径，旧数据降级合成保证不崩。
2. **中间推理流出**：经用户确认，打破原「中间节点 token 不暴露前端」约定 —— 中间推理随 token 流出、淡色展示、写完折叠。已同步更新 AGENTS.md。工具入参/原始结果仍经 `build_tool_label` 脱敏，不直接外发。
3. **reasoning/answer 渲染期判定**：不引入后端新事件，前端用「最后一个 text 段=最终回复」判定，契约最小化。
4. **reasoning 折叠时机**：流式写入中（loading 且为最后消息末段）展开，写完（后面来新段或 loading 结束）自动折叠，用户可手动覆盖。
5. **澄清问题仍留消息流**（历史完整），选项移出气泡只在浮层，避免选过后历史里悬空一排按钮。自定义答案走普通消息通道，后端零改动。

## 执行方式

Subagent-Driven Development：每任务派全新 implementer subagent + 任务后 spec/质量双审 + 修复循环。Task 1/3/8 触发修复轮次（DRY 复用、澄清分支对称收尾、aria-label 可访问性等），均复审通过。进度账本见 `.superpowers/sdd/progress.md`。
