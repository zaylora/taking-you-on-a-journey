# 移除独立上下文中间件模块

## 任务目标

- 删除 `backend/app/middleware/context.py`。
- 保留 `uv run dev` 启动所需的上下文 middleware 组装能力。
- 只做最小同步，不改变工具、SSE 或前端契约。

## 改动文件清单

| 文件 | 说明 |
| --- | --- |
| `backend/app/agent/build.py` | 将 middleware 列表组装放回 `_build_context_middleware()`。 |
| `backend/tests/agent/test_build_agent.py` | 改为验证 `app.agent.build._build_context_middleware()`。 |
| `backend/AGENTS.md` | 移除 `middleware/context.py` 的目录与依赖说明。 |
| `docs/20260701_backend_layout_cleanup/README.md` | 同步此前记录中关于 `middleware/context.py` 的描述。 |
| `docs/README.md` | 增加本次改动索引。 |

## 改动详情

- 删除独立的 `app.middleware.context` 模块，避免为一段 agent 专属组装逻辑新增文件。
- `agent/build.py` 重新直接导入 `CurrentTimePromptMiddleware`、`ToolResultPersistenceMiddleware`、`ContextEditingMiddleware`、`SummarizationMiddleware` 和摘要提示词。
- `_build_context_middleware()` 保留原阈值：工具清理 `trigger=16000`、`clear_at_least=5000`、`keep=4`，摘要 `tokens=40000` / `messages=28`，保留最近 `10000` tokens。

## 测试结果

- `cd backend && uv run pytest tests/agent/test_build_agent.py -q`：2 passed, 3 warnings。

## 相关讨论

- 用户明确要求删除 `backend/app/middleware/context.py`；本次采用“少一个模块”的实现方式。
- 当前上下文治理仍是 `agent/build.py` 的 agent 组装细节，未改变运行行为。
