# 动态工具调用文案

## 任务目标

让聊天气泡中的工具调用 pill 根据本次 tool call 参数动态展示中文进度，不再把 `research_xhs_travel_guide` 这类内部函数名直接暴露给用户；前端仍只渲染后端 SSE/历史消息里的 `label` 字段。

## 改动文件清单

| 文件 | 说明 |
| --- | --- |
| `backend/app/services/tool_labels.py` | 新增动态工具文案生成器 `build_tool_label`，按工具名和参数生成短中文 label，并为未知工具提供安全兜底。 |
| `backend/app/core/constants.py` | 移除旧的 `TOOL_LABELS` 静态工具名映射，保留 SSE 事件名与节点文案常量。 |
| `backend/app/graph/stream.py` | `on_tool_start` 从 LangChain 事件中读取工具入参并生成动态 label；`on_tool_end` 复用已记录的 label。 |
| `backend/app/services/message_history.py` | 历史会话聚合时用 tool call args 生成同样的动态 label，保持实时与回放一致。 |
| `backend/tests/test_tool_labels.py` | 新增动态 label 单测，覆盖小红书攻略、高德搜索、天气预算和未知工具兜底。 |
| `backend/tests/test_chat_stream.py` | 更新流式测试，验证 SSE `tool_call` 和落库 `tool_steps` 都使用动态 label。 |
| `backend/tests/test_session_aggregate.py` | 新增历史聚合测试，验证 replay 时能从 tool call args 生成上下文文案。 |
| `docs/superpowers/plans/2026-06-28-dynamic-tool-labels.md` | 记录实施计划与 TDD 步骤。 |

## 改动详情

- 没有给每个工具进度额外调用 LLM。原因是进度提示需要在工具开始时立刻出现；额外 LLM 会增加延迟、成本和不稳定性。实现上改为“参数驱动的动态中文文案”，例如：
  - `research_xhs_travel_guide(city=顺德, days=1, travel_style=美食)` → `研究顺德1天美食小红书攻略`
  - `search_restaurants(city=佛山, keywords=华盖路早茶)` → `搜索佛山餐厅：华盖路早茶`
  - 未知工具带城市参数 → `执行工具：广州`，无参数 → `执行工具`
- `stream.py` 在 `on_tool_start` 时读取 `ev["data"]["input"]`，生成 label 后写入本轮 `tool_steps` 并通过 SSE 发给前端。
- `on_tool_end` 优先复用对应 running step 中的 label，避免工具结束事件缺少入参时退化成另一种文案。
- `message_history.tool_steps()` 同样使用 `build_tool_label`，保证从 LangGraph checkpoint 重建历史时不会回到旧的 raw tool name。
- 旧的 `TOOL_LABELS` 静态映射已移除，避免出现“静态表”和“动态文案生成器”两套来源。

## 测试结果

- `cd backend && uv run pytest tests/test_tool_labels.py -q`：4 passed。
- `cd backend && uv run pytest tests/test_chat_stream.py::test_sse_events_persists_ui_history_matching_realtime_stream -q`：1 passed。
- `cd backend && uv run pytest tests/test_tool_labels.py tests/test_chat_stream.py tests/test_session_aggregate.py tests/test_sessions.py -q`：27 passed，4 warnings（第三方 deprecation）。
- `cd backend && uv run pytest tests/agent/test_prompt.py tests/agent/test_build_agent.py -q`：12 passed，3 warnings（第三方 deprecation）。

## 相关讨论

- 用户希望工具调用展示更动态、更智能，不要写死/显示内部函数名。
- 设计确认后选择后端生成动态 label，前端维持展示职责；相比每次进度都调 LLM，这个方案更快、更稳，也不会额外消耗模型 token。
