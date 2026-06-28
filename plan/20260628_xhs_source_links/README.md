# 小红书笔记来源链接

## 任务目标

在旅行规划对话中，将小红书搜索研究阶段采集到的笔记来源信息（笔记 ID、标题、链接）以可点击的链接形式追加到回复末尾，方便用户直接跳转原笔记。同时通过系统提示词明确告知模型：来源链接由系统自动附上，模型不要自行编造或重复粘贴笔记 URL。

## 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `backend/app/agent/state.py` | 修改 | TripState 新增 `xhs_sources` 字段，存储笔记来源记录列表 |
| `backend/app/agent/tools/xhs.py` | 修改 | 新增 `_build_note_url` 拼接笔记链接；新增 `_extract_source_records` 从搜索结果采集 id+xsec_token+title；新增 `_merge_xhs_sources` 跨轮累积去重；`research_xhs_travel_guide` 改为返回 Command 以写入 state |
| `backend/app/graph/stream.py` | 修改 | 新增 `render_xhs_sources` 渲染来源 Markdown；`sse_events` 流式结束后补发 token 追加「## 笔记来源」并拼进 final.answer |
| `backend/app/agent/prompt.py` | 修改 | 回复要求段末尾追加提示：来源链接由系统附上，模型不要自行编造 |
| `backend/tests/agent/test_state.py` | 修改 | 覆盖 xhs_sources 字段存在性 |
| `backend/tests/agent/test_tools.py` | 修改 | 覆盖 `_build_note_url`、`_extract_source_records`、Command 返回值 |
| `backend/tests/test_chat_stream.py` | 修改 | 覆盖 `render_xhs_sources` 渲染、sse_events 补发 token、仅本轮有新增才追加 |
| `backend/tests/agent/test_prompt.py` | 修改 | 覆盖新增提示文案 |

## 改动详情

### 1. state.py — 数据结构

在 `TripState`（AgentState 子类）中新增 `xhs_sources` 字段（`list`），每条记录包含 `note_id`、`xsec_token`、`title`、`type`、`url`。

### 2. xhs.py — 搜索阶段采集与写 state

- `_build_note_url(note_id, xsec_token)`：优先使用搜索结果 item 中的完整 URL，降级为拼接 `https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec_token}`。
- `_extract_source_records(search_result, *, limit=6)`：从搜索结果 items 中提取笔记级 `note_id`、`xsec_token`、`title`，按 limit 截取。
- `_merge_xhs_sources(existing, new_records, *, limit=6)`：跨轮累积去重（按 note_id 去重），总量上限 6 条。
- `research_xhs_travel_guide`：从返回 dict 改为返回 `Command(update={"xhs_sources": merged})`，让 LangGraph 将来源写入 state。
- `_research_command`：search 成功时调用 `_extract_source_records` 后构造 Command；search 失败时传空列表仍返回 Command（不更新 sources）。

### 3. stream.py — 流式追加来源
- `render_xhs_sources(sources, *, limit=6)`：将来源列表渲染为 Markdown 格式的「## 笔记来源」段落，每条一行 `[标题](url)`，标题缺失时兜底为「笔记」。
- `sse_events`：在流式 token 全部发送完毕后，检查 `xhs_sources` 是否有新增（通过 `len(xhs_sources) > prior_source_count` 判断），若有则补发一条包含来源 Markdown 的 token 事件，同时将来源拼接到 `final.answer`。

### 4. prompt.py — 提示词微调

在 `TRIP_AGENT_SYS` 的「## 回复要求」段末尾追加一句：

> 小红书笔记来源链接由系统在回复结尾自动附上，你不要自己编造或重复粘贴笔记 URL。

### 5. 测试覆盖

- `test_state.py`：验证 `xhs_sources` 默认值及赋值。
- `test_tools.py`：验证 `_build_note_url` 拼接逻辑、`_extract_source_records` 提取与去重、research 返回 Command。
- `test_chat_stream.py`：验证 `render_xhs_sources` 渲染格式、sse_events 补发 token、仅本轮有新增才追加、无新增时不追加。
- `test_prompt.py`：验证新增提示文案存在于提示词中。

## 测试结果

全功能 6 任务的相关测试全绿。全量 pytest 有 2 个预存失败（test_matrix.py 缓存测试、test_amap.py 诊断测试），与本功能无关，在功能基线即失败。

```
tests/agent/test_prompt.py: 10 passed
```

## 相关讨论

### 笔记级 xsec_token vs 用户级 xsec_token

小红书笔记链接需要 `xsec_token` 才能正常打开。关键发现：笔记级 xsec_token 只在搜索结果的 item 级出现（即 `search_result.items[].xsec_token`），而笔记详情 API（read 阶段）拿到的是 user 级 token，无法用于拼出可点击的笔记链接。因此必须在搜索阶段就采集 `note_id + xsec_token + title`，而不是等到 read 阶段。

### 前端流式追加机制

前端气泡的正文内容来自流式 token 累积，而非直接使用 `final.answer`。因此追加笔记来源时，必须在流式结束后额外补发一条 token 事件，让前端气泡能显示完整的来源信息。同时需要更新 `final.answer`，确保最终状态的一致性。

### 跨轮累积去重

用户可能在多轮对话中反复触发小红书搜索（如先搜攻略、再搜美食），每轮搜索可能返回相同笔记。使用 `_merge_xhs_sources` 按 `note_id` 去重，并设总量上限 6 条，避免重复和过长。

### 仅本轮有新增才追加

为避免每轮回复都重复附上相同的来源列表（尤其是没有新搜索的纯问答轮），通过 `prior_source_count` 追踪本轮开始前的来源数量，仅当本轮有新增时才触发追加。
