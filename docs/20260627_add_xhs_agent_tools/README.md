# 任务目标

把 `jackwener/xiaohongshu-cli` 接入后端 LangGraph agent，作为可调用的小红书只读工具，用于旅行灵感检索、笔记读取和评论分析。

# 改动文件

- `backend/app/agent/tools/xhs.py`
- `backend/app/agent/tools/__init__.py`
- `backend/app/agent/build.py`
- `backend/pyproject.toml`
- `backend/uv.lock`
- `backend/tests/agent/test_tools.py`

# 改动详情

- 新增 `xhs.py`，通过安全 argv 子进程调用 `xhs --json`，解析 CLI envelope，并处理缺少命令、超时、非 JSON 错误输出。
- 暴露只读/发现类工具：`xhs_status`、`xhs_search_notes`、`xhs_read_note`、`xhs_note_comments`、`xhs_hot_notes`、`xhs_user_profile`。
- 支持 `XHS_CLI_BIN` 覆盖命令入口，支持 `XHS_CLI_TIMEOUT_SECONDS` 调整调用超时。
- 将工具注册进 agent 的 `_TOOLS`，并在工具导出模块中统一导出。
- 增加 `xiaohongshu-cli>=0.6.4` 后端依赖并更新 `uv.lock`。
- 暂不暴露点赞、评论、发布、删除等写操作，避免旅行规划 agent 在普通对话中误触外部账号行为。
- 顺手修正两个旧测试的 monkeypatch 路径，让它们指向实际模块 `app.agent.tools.trip.amap`。

# 测试结果

- `uv run pytest tests/agent/test_tools.py tests/agent/test_prompt.py tests/agent/test_build_agent.py`
  - 结果：29 passed, 3 warnings
- `uv run xhs --help`
  - 结果：CLI 入口可正常启动并显示命令列表。

# 相关讨论

- 采用成熟 CLI 依赖承接小红书登录、签名、反风控和结构化输出能力，后端只做薄封装。
- 工具返回上游 CLI 的结构化结果，保留 `ok/data/error` envelope，方便 agent 判断是否需要提示用户登录或重试。
- 写操作可以后续单独接入，并建议加显式用户确认流程。
