# 工具结果过大立即落盘

## 任务目标

为高风险工具结果增加“超限立即落盘”能力：当底层工具返回内容过大时，完整结果写入后端本地文件，模型上下文只保留预览、`result_id` 和读取提示；同时新增只读分页工具，让 Agent 必要时按需读取落盘内容。

## 改动文件清单

| 文件 | 说明 |
| --- | --- |
| `backend/app/agent/tool_result_storage.py` | 新增大工具结果落盘、预览 envelope、安全分页读取纯逻辑 |
| `backend/app/agent/tools/persisted_result.py` | 新增 `read_persisted_tool_result` 只读工具 |
| `backend/app/agent/tools/xhs.py` | 小红书底层工具返回接入超限落盘 |
| `backend/app/agent/tools/__init__.py` | 导出读取落盘结果工具 |
| `backend/app/agent/build.py` | 注册读取落盘结果工具到 ReAct Agent |
| `backend/app/agent/prompt.py` | 补充 Agent 对 `persisted=true` 工具结果的处理规则 |
| `backend/app/core/config.py` | 新增落盘目录、阈值、预览长度配置 |
| `backend/app/services/tool_labels.py` | 新增读取落盘结果工具的中文进度文案 |
| `backend/tests/agent/test_tool_result_storage.py` | 覆盖落盘与安全读取纯逻辑 |
| `backend/tests/agent/test_tools.py` | 覆盖小红书大结果落盘与读取工具注册/调用 |

## 改动详情

- 新增 `maybe_persist_tool_result`：先把工具返回序列化为 JSON 字符串；未超过阈值时原样返回，超过阈值时写入 `tool_result_storage_dir`，并返回轻量 envelope。
- 新增 `read_persisted_tool_result_slice`：只允许读取配置目录内的单文件名 `result_id`，拒绝 `../` 等路径穿越；支持 `offset` / `limit` 分页读取。
- 新增 Agent 工具 `read_persisted_tool_result`，让模型看到 `persisted=true` 后可按需读取完整结果片段。
- 接入小红书底层工具：`xhs_search_notes`、`xhs_read_note`、`xhs_note_comments`、`xhs_hot_notes`、`xhs_user_profile`。`research_xhs_travel_guide` 已经返回结构化研究摘要，暂不额外落盘，避免把主路径复杂化。
- 保留现有 `ContextEditingMiddleware` / `SummarizationMiddleware`：新逻辑解决“单个工具结果刚返回就过大”，旧逻辑继续处理“历史上下文长期膨胀”。

## 测试结果

- `uv run pytest tests/agent/test_tool_result_storage.py tests/agent/test_tools.py tests/agent/test_build_agent.py -q`
  - 结果：`55 passed`

## 相关讨论

- 采用方案 C：新增通用落盘模块，但先只在高风险工具中显式调用，避免改动 LangChain tool 执行链。
- 第一版包含读取落盘结果工具，但读取范围严格限制在配置的本地目录内。
- 普通小结果行为保持不变；只有超过阈值时才改为 `persisted=true` envelope。
