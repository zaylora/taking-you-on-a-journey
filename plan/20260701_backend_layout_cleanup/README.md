# 后端目录归整执行记录

## 目标

执行 `docs/superpowers/specs/2026-07-01-backend-layout-cleanup-design.md`：

- 消除 `backend/app/graph/`。
- 建立 `backend/app/tools/actions`、`planning`、`clients` 三分层。
- 建立 `backend/app/middleware/`，并把大工具结果落盘中间件化。
- 同步文档与测试，不保存到 git。

## 执行要点

- 先跑后端基线，确认改动前测试为绿。
- 搬迁阶段按旧路径搜索驱动 import 重接。
- 落盘中间件阶段先写 `tests/middleware/test_tool_result_persistence.py`，确认红灯后实现。
- xhs 工具取消手动落盘，落盘职责统一交给 `ToolResultPersistenceMiddleware`。

## 验证

最终验证以 `cd backend && uv run pytest -q` 和旧路径残留检查为准。
