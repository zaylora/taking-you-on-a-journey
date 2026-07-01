# 后端目录归整与大工具结果落盘中间件化

## 任务目标

- 消除 ReAct 重构后遗留的 `graph/` 疤痕层，把 SSE 桥接放回 `api/`，把 LangGraph 入口放回 `agent/build.py`。
- 将工具能力域归整为 `tools/actions`、`tools/planning`、`tools/clients` 三层。
- 将大工具结果落盘从 xhs 单点手动处理提升为统一的 `ToolResultPersistenceMiddleware`。
- 不改 SSE 契约，不改前端，不提交到 git。

## 改动文件清单

| 类型 | 文件 |
| --- | --- |
| 目录归整 | `backend/app/api/chat_stream.py`、`backend/app/agent/build.py`、`backend/langgraph.json` |
| 工具能力层 | `backend/app/tools/` |
| 中间件 | `backend/app/middleware/current_time.py`、`backend/app/middleware/tool_result_persistence.py` |
| 落盘基建 | `backend/app/tools/tool_result_storage.py` |
| xhs 工具 | `backend/app/tools/actions/xhs.py` |
| 测试 | `backend/tests/agent/*`、`backend/tests/test_amap.py`、`backend/tests/test_chat_stream.py`、`backend/tests/middleware/test_tool_result_persistence.py` |
| 文档 | `AGENTS.md`、`backend/AGENTS.md`、`docs/README.md` |

## 改动详情

- `graph/stream.py` 迁到 `api/chat_stream.py`，`graph/builder.py` 的 `build_graph`/`make_graph` 合并进 `agent/build.py`。
- 原 `agent/tools/` 迁到 `tools/actions/`，原 `agent/itinerary/` 迁到 `tools/planning/`，原 `utils/amap.py` 迁到 `tools/clients/amap.py`。
- 新增 `tools/registry.py` 作为工具注册中心，`agent/build.py` 改为使用 `ALL_TOOLS`。
- `agent/build.py` 维护 `_build_context_middleware()`，集中组装时间注入、落盘、上下文清理和摘要。
- `CurrentTimePromptMiddleware` 放在 `middleware/current_time.py`，时间 payload、工具 schema 和 system prompt 构造放到 `tools/time_context.py`。
- 新增 `ToolResultPersistenceMiddleware`，统一拦截 `ToolMessage` 和 `Command(update.messages)` 中的超大工具结果并落盘。
- xhs 工具取消手动落盘，直接返回原始业务结果，避免和 middleware 二次落盘。

## 测试结果

- 基线：`cd backend && uv run pytest -q`，152 passed, 4 warnings。
- 搬迁中专项验证：
  - `uv run pytest -q tests/test_chat_stream.py tests/agent/test_build_agent.py`
  - `uv run pytest -q tests/agent/test_tools.py tests/agent/test_prompt.py tests/agent/test_budgeting.py tests/agent/test_diffing.py tests/agent/test_itinerary_fill.py tests/agent/test_itinerary_schemas.py tests/agent/test_lodging.py tests/agent/test_matrix.py tests/agent/test_optimizer.py tests/test_amap.py`
  - `uv run pytest -q tests/middleware/test_tool_result_persistence.py tests/agent/test_tool_result_storage.py tests/agent/test_tools.py tests/agent/test_build_agent.py`

## 相关讨论

- 不新增 `orchestrator.py`、`planner.py`、`executor.py`、`router.py` 空壳；这些职责由 LangGraph `create_agent` 内建承载。
- `tools/registry.py` 是工具编目，不承担运行时 tool routing。
- 大工具结果落盘是唯一行为变更，因此新增了 `ToolMessage`、`Command`、豁免工具、async 路径和读回验证测试。
