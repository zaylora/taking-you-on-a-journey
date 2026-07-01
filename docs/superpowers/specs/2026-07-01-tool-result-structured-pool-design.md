# 工具结果上下文瘦身：结构化记录池 + 长文本可回溯占位符（分治）设计

- 日期：2026-07-01
- 范围：解决**痛点 1（上下文膨胀）**——工具返回的时间/地点/路线等结果一进上下文就滞留、多轮累积撑爆窗口。按数据类型分治：能结构化的走记录池，不能结构化的长文本借鉴 Hermes 的"旧结果转占位符 + 可回溯"。
- 不含：**痛点 2（决策依据溯源）**，留作下一期（方向已倾向 Hermes 式"七段式结构化摘要 + 迭代更新 + 回溯工具"，见 §9）。

## 1. 背景与真实痛点

当前 agent 调用工具后，结果以 `ToolMessage` 进入 `messages`（模型上下文）。用户观察到的现象：**查到的时间、地点（POI）这类结果一直留在上下文里，多轮下来越堆越大。**

根因是这些结果"两头不靠"：

1. **不够大到落盘**：`ToolResultPersistenceMiddleware` 落盘阈值 `tool_result_persist_threshold_chars = 20000` 太高，POI/时间结果只有几 KB，够不到，于是原文全留在上下文。
2. **不够旧到被清**：`ContextEditingMiddleware(ClearToolUsesEdit)` 只清"最近 4 个之外"的旧工具结果，且要累积到 `trigger=16_000` tokens 才触发，中小结果长期滞留。

## 2. 借鉴 Hermes 的核心思路

Hermes 渐进式压缩的核心动作一句话概括：**"用过的原始结果别留在上下文里，转成占位符/摘要，要用时再取回。"**

本设计据此分治，并区分两种更彻底 / 更合适的处理：

- Hermes 治的是"**已进上下文的东西怎么瘦身**"（事后 prune 成占位符 + 结构化摘要）。
- 记录池治的是"**让它压根别进上下文**"（进来即拆记录进池，上下文只留目录）。

对能结构化的结果，**记录池更彻底**（不进 > 进了再清）；对无法结构化的长文本，**Hermes 式占位符 + 可回溯更合适**。

## 3. 分治策略

| 数据类型 | 例子 | 处理 | 效果 |
|---|---|---|---|
| **能结构化** | 时间、POI/地点、路线 | 进**记录池**，上下文只留精简目录（§5） | 从源头掐，原文不进上下文 |
| **不能结构化的长文本** | xhs 攻略正文、评论 | 借鉴 Hermes：**用过即转占位符 + 落盘可回溯**（§6） | 事后清，但能按 id 翻回来 |

## 4. 污染数据形态

| 工具 | 数据 | 天然主键 | 归类 |
|---|---|---|---|
| `search_attractions` / `search_restaurants` | POI 列表 | `poi_id`（高德） | 结构化 → 记录池 |
| `get_current_time` | 时间信息 | — | 结构化（本就很小，见 §5.7） |
| `plan_route` | 高德巨型 route 结构 | 起讫点+mode | 结构化 → 记录池（下期） |
| `research_xhs_travel_guide` / `xhs_read_note` / `xhs_note_comments` | 攻略正文/评论 | `note_id` | 非结构化长文本 → 占位符可回溯（下期） |

`poi_id` 已是项目里"卡片 ↔ 地图联动"的主键，天然适合做记录池索引。

## 5. 结构化记录池（本期核心）

### 5.1 思路

工具查到列表后：

1. **拆成一条条记录进"池子"**，按 `poi_id` 索引，池子存进 `TripState`。
2. 返回给上下文的**只有一张精简目录** `[{poi_id, name, type}]`，每条一行，不含地址、坐标等详情。
3. LLM 要用某条详情时，调 `get_poi(poi_id)` 精确取一条。

上下文里永远只有"目录"，详情在池子里躺着，要哪条取哪条。

### 5.2 State 字段

`TripState`（`backend/app/agent/state.py`）新增记录池字段。同一 step 可能多个搜索工具并发写，**必须配 reducer 合并去重**（对齐现有 `xhs_sources` 的 `merge_xhs_sources` 模式）：

```python
# 记录池：按主键索引的原始数据详情，供 InjectedState 精确取用、前端直接展示。
poi_pool: Annotated[dict, merge_records]      # key = poi_id
```

### 5.3 reducer

`backend/app/agent/reducers.py` 新增 `merge_records(existing, incoming)`：按主键 upsert（新值覆盖同键旧值），对 None/非 dict 输入降级为空 dict。纯函数，单独单测。

### 5.4 搜索工具改造

`search_attractions` / `search_restaurants` 从"返回完整列表"改为返回 `Command`：

- `update.poi_pool`：`{poi_id: 完整POI}` 增量，交 reducer 合并。
- `update.messages`：一条 `ToolMessage`，内容是**精简目录** `[{poi_id, name, type}]` + 提示"详情在池中，需要时调 get_poi(poi_id)"。

工具本身即返回精简目录，不再依赖 `ToolResultPersistenceMiddleware` 兜底。

### 5.5 取用工具

新增 `get_poi`（`backend/app/tools/actions/`）：

```python
@tool
async def get_poi(poi_id: str, state: Annotated[dict, InjectedState]) -> dict:
    """按 poi_id 从记录池精确取一条 POI 详情。"""
```

从 `state["poi_pool"]` 直接取，命中返回详情，未命中返回结构化错误（提示先搜索）。零文件 IO。

### 5.6 系统提示

`backend/app/agent/prompt.py` 增补：搜索类工具只返回目录；需要某条详情（地址、坐标、营业信息）时调 `get_poi(poi_id)`；不要凭目录里的名字臆测详情。

### 5.7 时间工具

`get_current_time` 结果本就很小（一条时间字符串），不必入池；但当前 `CurrentTimePromptMiddleware` 已在系统提示注入时间——需确认是否存在"每轮重复注入 / 工具重复调用"导致的时间信息累积，若有则改为只注入一次或按需。作为本期附带排查项。

## 6. 长文本可回溯占位符（借鉴 Hermes，本期打地基）

针对 xhs 攻略正文这类无法结构化的长文本：

- **调低落盘阈值 / 白名单强制落盘**：对 xhs 等长文本工具，不必等 20k，命中即落盘，上下文只留预览 + `result_id`（复用现有 `tool_result_storage.py` 机制）。
- **旧结果转占位符**：借鉴 `_prune_old_tool_results`——用过的旧长文本 `ToolMessage` 在超阈值后替换为占位符（现有 `ContextEditingMiddleware` 已具雏形，本期只调参，不重写）。
- **可回溯**：保留 `read_persisted_tool_result(result_id, offset, limit)` 作为翻回原文的手段。

本期只对 xhs 工具**调低落盘阈值**（配置项或工具级白名单），完整的 prune 策略调优随下期推进。

## 7. 数据流

```
search_restaurants(city, kw)
  → amap.search_poi → [POI...]
  → Command(update={
       poi_pool: {poi_id: POI...},        # 详情进池（reducer 合并）
       messages: [ToolMessage(精简目录)]   # 上下文只见目录
    })
...（LLM 看到目录，决定要哪条）...
get_poi(poi_id) → InjectedState 读 poi_pool[poi_id] → 返回该条详情
```

## 8. 错误处理

- `get_poi` 未命中：`{ok: false, error: {code: "poi_not_found", hint: "先调用 search_* 搜索"}}`，不抛。
- 搜索为空：目录 `[]`，`poi_pool` 不写，`ToolMessage` 说明空结果。
- reducer 非法输入：降级空 dict，不崩。

## 9. 分期

- **本期（先跑通）**：`poi_pool` + `merge_records` + `search_attractions/search_restaurants` 改造 + `get_poi` + 提示词 + 单测；附带排查时间注入累积（§5.7）；对 xhs 工具调低落盘阈值（§6）。
- **下期推广**：`route_pool`（`plan_route`）入池；xhs 长文本 prune 策略完整调优。
- **再下期（另立 spec，痛点 2）**：借鉴 Hermes 的**七段式结构化摘要模板**（含 `## Key Decisions`，强制保留决策理由）替换 `TRIP_SUMMARY_PROMPT`、**迭代更新摘要**（基于上一版增量）、**回溯搜索工具**（从旧 checkpoint / 归档翻被压缩掉的原文）。注：LangGraph 的 `checkpointer` + `thread_id` 已等价 Hermes 的 `parent_session_id` 链，故不引入 session 分裂。

## 10. 测试

- `merge_records`：纯函数单测，覆盖空、同键 upsert、并发多写、非法输入。
- `search_restaurants` 改造：对 `amap.search_poi` 打桩，断言返回 `Command`、`poi_pool` 含完整 POI、`ToolMessage` 只含精简目录（不含 address/坐标）。
- `get_poi`：命中 / 未命中两条路径。
- 回归：改造后小目录不触发 `ToolResultPersistenceMiddleware`；xhs 调低阈值后长文本按预期落盘。
- 全量 `uv run pytest -q` 绿。

## 11. 不做（YAGNI）

- 不做通用 kv 存储抽象层，只按现有业务对象（POI/route/note）建池。
- 不重写 `ContextEditingMiddleware` / `SummarizationMiddleware`，本期至多调参。
- 不在本期改前端（`poi_pool` 结构对前端友好，透出留后续）。
- 不引入 session 分裂 / `parent_session_id`。
- 本期不处理决策依据溯源。
