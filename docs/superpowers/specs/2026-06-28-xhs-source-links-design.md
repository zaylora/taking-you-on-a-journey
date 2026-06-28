# 小红书笔记来源链接 — 设计文档

日期:2026-06-28
分支:feature/add_xiaohongshu_search

## 任务目标

生成旅行攻略时,在回复结尾附上本次研究所用的小红书笔记来源链接,让用户可以点开溯源。链接必须真实可点开、不被 LLM 篡改。来源数据在搜索阶段就采集并写入 state。

## 背景与现状

- 小红书研究的核心工具是 `research_xhs_travel_guide`([backend/app/agent/tools/xhs.py](../../../backend/app/agent/tools/xhs.py)),内部流程:搜索多个关键词 → `_extract_note_targets` 提取 targets → 读笔记详情 → LLM 提炼成 `XhsTravelBrief`。
- 现状 `source_notes` 只记 `{target, ok}`,**不写回 state**,也不流到前端。
- `TripState`([backend/app/agent/state.py](../../../backend/app/agent/state.py))无来源字段。
- 最终回复正文由 LLM 流式生成,前端用 `renderMarkdown` 渲染(markdown 链接可点击)。

### 关键技术发现(决定方案形态)

通过实跑 `xhs` CLI 确认:

1. **搜索结果不返回现成 url**。每个 item 结构为 `{id, xsec_token, note_card.display_title, note_card.type}`。
2. **能点开的笔记链接需要 id + xsec_token 两者**:
   `https://www.xiaohongshu.com/explore/<id>?xsec_token=<token>&xsec_source=pc_search`。
   只有 id 没 token 的链接打开会报错。
3. **笔记级 xsec_token 只在搜索结果 item 级**。`xhs read` 返回的 `note_card.user.xsec_token` 是**用户的** token,不是笔记的,不能用于构造笔记 URL。
4. 因此**必须在搜索阶段采集** `id + xsec_token + title`,读笔记阶段拿不到正确 token。

## 设计决策(已与用户确认)

| 决策点 | 选择 |
|--------|------|
| 呈现方式 | 后端确定性追加:搜索时存 state,流式结束后由后端取出并以 markdown 列表追加,链接不经 LLM |
| 来源范围 | 仅 `research_xhs_travel_guide`(攻略研究主路径)实际读取的笔记 |
| 链接格式 | 优先完整 URL(id + xsec_token),拿不到 token 降级为 `explore/<id>` |

## 数据流

三段式:

1. **搜索阶段采集**:`research_xhs_travel_guide` 搜索每个关键词时,从结果 item 提取结构化来源记录 `{note_id, xsec_token, title, type, url}`,只保留实际进入 `targets`(被读取)的笔记。`url` 抓取时即拼好,token 缺失则降级。
2. **写回 state**:工具从「返回 dict」改为「返回 `Command`」,通过 `Command(update={"xhs_sources": [...], "messages": [ToolMessage(...)]})` 写入新增的 `TripState.xhs_sources`(跨轮累积 + 按 note_id 去重)。与 `finalize_plan` / `compute_budget_tool` 写法一致。
3. **结尾追加**:后端从 state 取 `xhs_sources`,以 `## 笔记来源` markdown 列表追加到回复末尾。

### 关键约束:前端正文来自流式 token

前端聊天气泡正文由流式 token 累积(`appendToLastMessage`),**不是**用 `final` 事件里的 `answer`。因此「追加到结尾」不能只改 `final.answer` —— 那样气泡里看不到。

正确做法:模型流式结束后、`final` 事件之前,stream 层**补发若干 `token` 事件**把 `## 笔记来源` 文本接到气泡末尾;同时 `final.answer` 带上完整文本(用于会话持久化/重载)。

## 后端改动

### `backend/app/agent/tools/xhs.py`

新增链接提取:
- `_build_note_url(note_id, xsec_token)`:有 token 拼带 token 的 explore URL,否则降级为 `explore/<id>`。
- `_extract_source_records(search_result, *, limit)`:遍历搜索结果 item,产出 `{note_id, xsec_token, title, type, url}`。复用 `_walk_values`,从 item 级取 `id`/`xsec_token`、从 `note_card` 取 `display_title`/`type`。

工具改为写 state:
- `research_xhs_travel_guide` 在搜索循环里同步收集来源记录,按 `note_id` 去重,最终只保留进入 `targets` 的笔记。
- 签名加 `tool_call_id: Annotated[str, InjectedToolCallId]` 与 `state: Annotated[dict, InjectedState]`,返回类型改为 `Command`。
- 与 state 已有 `xhs_sources` 按 `note_id` 合并去重(跨搜索/跨轮累积)。
- 原 envelope(`{ok, data, meta}`)序列化进 `ToolMessage`,内容不变,LLM 侧无感知。

### `backend/app/agent/state.py`

- `TripState` 增加 `xhs_sources: list`。

### `backend/app/graph/stream.py`

- 模型流式结束后,从 `snap.values` 取 `xhs_sources`;若非空且本轮有 AI 文本,渲染:
  ```
  \n\n## 笔记来源\n
  - [标题](url)
  ...
  ```
  标题缺失用「小红书笔记」兜底。
- 这段 markdown 拆成 `token` 事件补发(接到气泡),并拼进 `final.answer`。
- 幂等保护:只在本轮 `xhs_sources` 有更新时追加,避免纯问答轮重复贴来源。

## 边界与错误处理

- **CLI 失败 / 无结果**:工具仍返回 `Command`,但 `xhs_sources` 不更新,不影响主流程。
- **拿不到 xsec_token**:降级为无 token 的 explore URL。
- **标题缺失**(如 video 类 `display_title` 为空):兜底「小红书笔记」。
- **跨轮累积**:state 按 note_id 去重,只增不重复。
- **纯问答轮**:不追加(仅本轮 `xhs_sources` 有更新才追加)。
- **数量上限**:最多展示 6 条(对齐 `_RESEARCH_NOTE_LIMIT`)。

## 测试

- `_build_note_url`:有/无 token 两分支。
- `_extract_source_records`:嵌套搜索结果正确提取 id/token/title,去重。
- `research_xhs_travel_guide`:mock CLI,断言返回 `Command`、`xhs_sources` 正确写入且与 targets 对齐。
- `stream.py`(`test_chat_stream.py` 补例):state 有 `xhs_sources` 时,补发 token 含 `## 笔记来源` 且 `final.answer` 含链接;无 sources 时不追加。
- 现有 `test_tools.py` 中断言 `research_xhs_travel_guide` 返回 dict 的用例,同步改为断言 `Command`。

## 改动文件清单

- `backend/app/agent/tools/xhs.py`(修改)
- `backend/app/agent/state.py`(修改)
- `backend/app/graph/stream.py`(修改)
- `backend/tests/agent/test_tools.py`(修改)
- `backend/tests/test_chat_stream.py`(修改)
