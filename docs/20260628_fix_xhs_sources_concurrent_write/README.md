# 修复 xhs_sources 并发写入冲突（InvalidUpdateError）

## 任务目标

修复生产环境 `/api/chat` 偶发崩溃：

```
langgraph.errors.InvalidUpdateError: At key 'xhs_sources':
Can receive only one value per step. Use an Annotated key to handle multiple values.
```

根因：`TripState.xhs_sources` 声明为普通 `list`，LangGraph 用 `LastValue` 通道，**同一 step 只允许写一次**。当 ReAct 一轮里 LLM 并行调用多个会写 `xhs_sources` 的 tool（如多个 `research_xhs_travel_guide`）时，多个 `Command(update={"xhs_sources": ...})` 同步写同一 key → 抛错。

`langgraph dev` 不报错只是概率问题：那几次模型恰好每轮只调一个该类 tool，未触发并发写，并非代码无隐患。

## 改动文件

- 新增 `app/agent/reducers.py` — 抽出 `merge_xhs_sources` reducer（独立模块，避免 state ↔ tools 循环导入）
- 修改 `app/agent/state.py` — `xhs_sources` 改为 `Annotated[list, merge_xhs_sources]`
- 修改 `app/agent/tools/xhs.py` — tool 只写本轮增量；删除不再使用的 `InjectedState` 注入与 `_merge_xhs_sources`
- 新增 `tests/agent/test_reducers.py` — reducer 去重/截断/并发增量合并单测
- 修改 `tests/agent/test_tools.py` — 原「读 state 合并」测试改为「只写增量」契约

## 改动详情

### 1. reducer 抽到独立模块
`merge_xhs_sources(existing, new) -> merged`：按 `note_id` 去重、保留先出现者、截断到 `XHS_SOURCE_LIMIT=6`。形状即 reducer 签名 `(累积值, 单次增量) -> 合并值`。

### 2. state 带 reducer
```python
xhs_sources: Annotated[list, merge_xhs_sources]
```
同一 step 多个 tool 各写增量时，LangGraph 依次以 `(累积, 增量)` 调用 reducer 合并，规避并发写冲突。

### 3. tool 只写增量
原实现「读旧 state → 合并 → 写完整列表」在并发下会互相覆盖。改为只写本轮 `new_records`，合并/去重/截断全交给 reducer。`research_xhs_travel_guide` 内部跨关键词去重逻辑保留。`InjectedState` 不再需要，连同 `state` 形参一并删除。

## 测试结果

- 新增 + 受影响套件全过：`test_tools.py / test_reducers.py / test_state.py / test_chat_stream.py / test_stream_react.py / test_build_agent.py` → 61 passed
- `make_graph()` 正常构图，无循环导入，`xhs_sources` 注解已挂上 reducer
- 全量 `pytest`：111 passed，2 failed（`test_matrix` / `test_amap`，`git stash` 验证为改动前既存失败，与本次无关）

## 相关讨论

- **为什么不在 tool 内加锁/读最新 state**：InjectedState 是 step 开始时的快照，并发 tool 读到的是同一份旧值，无法靠它解决。reducer 是 LangGraph 官方推荐的并发写合并机制。
- **stream.py 的 `prior_source_count` 判断**：依赖「合并后总数变大」判断有无新来源；累积仍由 reducer 单调增长，逻辑不受影响（相关测试已通过）。
- **循环导入**：state.py 若直接 import xhs.py 会成环（build.py 同时引 state 与 tools），故 reducer 单独成模块。
