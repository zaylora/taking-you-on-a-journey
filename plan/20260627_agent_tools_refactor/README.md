# Agent 工具检索修复与目录整理

## 任务目标

排查 LangSmith Studio 线程里检索工具全部返回空数组的问题，并增强工具层的可诊断性与容错能力；随后整理 `backend/app/agent` 目录，让 Agent 工具、规划算法和领域纯函数分层更清楚。

## 根因与观察

- 目标 Studio thread 中 `search_attractions` / `search_restaurants` 的 `ToolMessage.content` 都是 `[]`，`get_weather` 降级为 `source=climate`，后续 `model` 节点又因上游 LLM `APIError` 停止。
- 当前环境下用同一个 `127.0.0.1:51170` 服务重新跑最小复现，广州景点检索能正常返回 20 条，说明旧 thread 里的空结果已经被 checkpoint 固化，不代表当前稳定复现。
- 高德 wrapper 原先把异常全部吞成 `[]` / `{}` / climate 降级，Studio 只能看到“工具成功但为空”，看不到 `infocode/info/count` 或网络异常类型。
- 高德 POI 查询对参数较敏感：长串 POI 名作为一个 `keywords` 命中不稳定，短关键词或拆分查询更可靠。

## 改动文件

### 后端工具与目录

- `backend/app/tools/amap.py`
- `backend/app/tools/__init__.py`
- `backend/app/agent/tools/__init__.py`
- `backend/app/agent/tools/trip.py`
- `backend/app/agent/tools/itinerary.py`
- `backend/app/agent/tools/lodging.py`
- `backend/app/agent/tools/budget.py`
- `backend/app/agent/tools/time.py`
- `backend/app/agent/tools/utils.py`
- `backend/app/agent/itinerary/*`
- `backend/app/agent/itinerary/routing/*`

### 测试

- `backend/tests/test_amap.py`
- `backend/tests/agent/test_tools.py`
- `backend/tests/agent/test_budgeting.py`
- `backend/tests/agent/test_diffing.py`
- `backend/tests/agent/test_lodging.py`
- `backend/tests/agent/test_matrix.py`
- `backend/tests/agent/test_optimizer.py`
- `backend/tests/agent/test_itinerary_schemas.py`

## 改动详情

### 1. 高德 wrapper 增加诊断日志

在 `app.tools.amap` 中对以下情况记录不含 key 的日志：

- 高德返回 `status != 1`
- POI / geocode / route / distance 返回空
- 请求异常或天气降级

日志包含 `city`、`keywords`、`type`、`count`、`infocode`、`info`、异常类型等定位信息，但不输出 `AMAP_WEB_KEY`。

### 2. 检索工具增加参数提醒与低命中 fallback

`search_attractions` / `search_restaurants` 增加独立 args schema，提示模型：

- `city` 优先传地级市或高德可识别城市名。
- 行政区信息放到 `keywords` 里辅助限定。
- `keywords` 优先短关键词，不要一次塞很多 POI / 店名。
- 多个明确目标应分多次调用。

工具内部保留返回 `list` 的原契约。若整串关键词命中少于阈值，会自动按空格、顿号、逗号等拆分关键词补查，并去重合并；补到够用即停止，避免过度触发高德 QPS 限制。

### 3. Agent tools 拆成包

原 `backend/app/agent/tools.py` 拆为 `backend/app/agent/tools/` 包：

```text
agent/tools/
  __init__.py   # 统一 re-export，保持原导入路径兼容
  trip.py       # search/weather/route tools + schema
  itinerary.py  # assemble_itinerary + schema
  lodging.py    # assign_hotels + schema
  budget.py     # compute_budget_tool / finalize_plan
  time.py       # get_current_time
  utils.py      # parse_jsonish_string 等共享 helper
```

`app.agent.tools` 仍然导出原工具名，`build.py` 的工具注册方式不需要变化。

### 4. 行程业务逻辑收进 itinerary

行程相关的 schema、住宿、预算、diff 纯函数统一放到 `agent/itinerary/`。这个包表达的是业务对象和确定性业务计算，不是 LangChain tool，也不是 Agent 自身的“计划器”。

```text
agent/itinerary/
  schemas.py
  lodging.py
  budgeting.py
  diffing.py
```

### 5. 路线算法收进 itinerary/routing

确定性路线编排流水线移动到 `agent/itinerary/routing/`：

```text
agent/itinerary/routing/
  assembler.py
  matrix.py
  optimizer.py
  prefilter.py
```

这些模块只负责候选筛选、距离矩阵、OR-Tools 求解和 day plan 骨架装配。

这样 `agent/` 根目录只保留 Agent 装配、提示词、状态和时间上下文。

## 当前目录形态

```text
backend/app/agent/
  build.py
  prompt.py
  state.py
  time_context.py

  tools/
    __init__.py
    trip.py
    itinerary.py
    lodging.py
    budget.py
    time.py
    utils.py

  itinerary/
    schemas.py
    lodging.py
    budgeting.py
    diffing.py

    routing/
      assembler.py
      matrix.py
      optimizer.py
      prefilter.py
```

`backend/app/tools/` 现在只保留外部服务封装：

```text
backend/app/tools/
  __init__.py
  amap.py
```

## 测试结果

- `cd backend && uv run pytest tests/agent/test_tools.py tests/test_amap.py -q`：23 passed。
- `cd backend && uv run pytest tests/agent/test_tools.py tests/agent/test_optimizer.py tests/agent/test_matrix.py -q`：25 passed。
- `cd backend && uv run pytest -q`：63 passed，4 warnings。

## 相关讨论

- 不把工具返回值改为 `{items, warning}`，避免影响 `assemble_itinerary` 等下游工具的 POI 数组契约。
- schema 跟对应 tool 放在同一个模块里，因为它们是 LLM tool-call 参数契约，而不是通用业务 DTO。
- `app.tools.amap` 定位为外部高德服务 wrapper；`app.agent.tools.*` 定位为 Agent 可调用的 LangChain tools。

## 后续建议

- 如需进一步保持旧 import 路径兼容，可增加轻量 alias 模块；当前代码和测试已全部迁移到新路径。
- 可考虑在日志配置中为 `app.tools.amap` 设置更明确的输出格式，方便从 LangGraph dev 进程中直接定位高德空结果。
- 如未来工具继续增加，优先按 `agent/tools/<domain>.py` 方式扩展，不再把实现堆回 `tools/__init__.py`。
