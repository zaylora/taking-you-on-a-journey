# 后端代码规范

## 编码规范

- 编码时，要考虑项目架构的抽象性。
- 当前后端是聚焦旅行规划的单 Agent 应用，按真实需求长出分层，不预建空壳文件。
- 修改目录结构时，以当前真实依赖方向为准，不把通用平台模板照搬成空目录。

## 当前目录结构

```
app/
├── main.py                    # FastAPI 入口，挂载路由、checkpointer、session_store、agent
├── api/
│   ├── chat.py                # /api/chat SSE 入口
│   ├── chat_stream.py         # LangGraph astream_events -> SSE 事件桥接
│   └── sessions.py            # 会话查询与快照
├── agent/
│   ├── build.py               # create_agent 组装：模型、工具清单、middleware 列表、state_schema
│   ├── prompt.py              # 旅行规划 agent 与工具专用提示词
│   ├── reducers.py            # 并发 state 写入 reducer
│   └── state.py               # TripState
├── middleware/
│   ├── current_time.py        # 每次模型调用前注入当前时间 system prompt
│   └── tool_result_persistence.py  # 超大工具结果统一落盘
├── tools/
│   ├── registry.py            # ALL_TOOLS 工具注册中心
│   ├── time_context.py        # 当前时间 payload、时间工具参数、动态 system prompt 构造
│   ├── tool_result_storage.py # 工具结果落盘与分页读取
│   ├── actions/               # Agent 可直接调用的 @tool
│   ├── planning/              # 预算、diff、行程填充、住宿、路线优化等纯计算能力
│   └── clients/               # 高德等外部服务客户端
├── core/                      # 配置与常量
├── llm/                       # LLM 工厂
├── schemas/                   # API 层 Pydantic schema
└── services/                  # 会话存储、消息历史、工具展示标签等服务
```

`app/agent/` 只放“agent 大脑”相关资产：组装、提示词、state 和 reducer。工具能力、外部客户端、工具结果落盘、当前时间工具上下文不放在 `agent/` 下。

## 架构映射

本项目使用 LangGraph `create_agent` 组装 ReAct agent，通用大型 Agent 平台里的若干概念由框架承载：

| 骨架概念                | 本项目承载位置                                    |
| ----------------------- | ------------------------------------------------- |
| orchestrator（总调度）  | `create_agent` 本身，由 `app/agent/build.py` 组装 |
| planner（LLM 任务拆解） | 模型 + `app/agent/prompt.py` 的 system prompt     |
| executor（工具执行）    | `create_agent` 内建 ToolNode                      |
| router（tool routing）  | `create_agent` 内建条件边                         |
| state（状态机）         | `app/agent/state.py` 的 `TripState`               |
| schema（内部结构）      | `app/schemas/` + `app/tools/planning/schemas.py`  |

不要为 `orchestrator`、`planner`、`executor`、`router` 新建空壳文件；除非后续真的脱离 `create_agent` 或有明确业务代码可承载。

## 依赖方向

- `agent/build.py` 负责 agent 组装，并在 `_build_context_middleware()` 中维护 middleware 列表。
- `middleware/current_time.py` 依赖 `tools/time_context.py` 生成动态 system prompt。
- `middleware/tool_result_persistence.py` 依赖 `tools/tool_result_storage.py` 执行落盘。
- `tools/actions/*` 可以依赖 `tools/planning/*`、`tools/clients/*`、`tools/time_context.py` 和 `agent/prompt.py`。
- `tools/planning/*` 应尽量保持纯函数；需要外部路线距离时只通过 `tools/clients/amap.py`。
- `tools/clients/*` 不反向依赖 `agent`、`middleware` 或 API 层。

## 工具能力分层

- `tools/actions/`：只放 LangChain `@tool` 入口，负责参数 schema、状态写回和降级输出。
- `tools/planning/`：放可单测的领域算法和结构化 schema，避免副作用。
- `tools/clients/`：封装外部服务调用、限流错误和脱敏日志。
- `tools/registry.py`：集中声明 `ALL_TOOLS`，新增 agent tool 只在这里登记一次。

## 横切能力

- 当前时间注入由 `middleware/current_time.py` 负责；时间 payload 与参数 schema 在 `tools/time_context.py`。
- 大工具结果落盘由 `middleware/tool_result_persistence.py` 统一处理；落盘与分页读取实现位于 `tools/tool_result_storage.py`。
- 普通工具不手动落盘，避免和 middleware 二次处理。
