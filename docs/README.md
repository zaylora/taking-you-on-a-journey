# 改动记录索引

| 日期 | 目录 | 概述 |
| --- | --- | --- |
| 2026-06-30 | `docs/20260630_route_connectivity/` | 修复当天景点到餐饮缺交通、旧会话交通缺段、总览地图跨天不连线和高德 QPS 限流导致后半段缺线的问题。 |
| 2026-07-01 | `docs/20260701_backend_layout_cleanup/` | 归整后端 `graph`、`tools`、`middleware` 目录，并将大工具结果落盘提升为统一中间件。 |
| 2026-07-01 | `docs/20260701_remove_context_middleware_module/` | 移除独立 `middleware/context.py`，将上下文 middleware 组装保留在 `agent/build.py`。 |
| 2026-07-01 | `docs/20260701_agent_state_comments/` | 为后端 `TripState` 业务字段补充中文注释，说明各字段用途。 |
| 2026-07-01 | `docs/20260701_sessions_comments/` | 将会话接口中的英文 docstring 改为中文说明。 |
