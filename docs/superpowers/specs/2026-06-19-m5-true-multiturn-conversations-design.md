# M5 设计：真正多轮对话 + 多会话 + SQLite Checkpointer

- 日期：2026-06-19
- 里程碑：M5（真正多轮对话体验）
- 范围：前端新增会话列表与新建会话按钮；后端把会话作为一等资源；LangGraph 从 `MemorySaver` 升级为 SQLite 持久化 checkpointer；节点显式读取历史消息与上轮行程，支持追问、修改、局部重排、重新规划
- 验收标准：用户能新建多个独立对话；刷新页面/后端重启后同一 `thread_id` 可恢复；用户能基于上一轮说“把第二天改轻松一点”“换一家酒店”“预算降到 3000”，系统增量修改而不是从零遗忘

## 决策摘要

| 决策点 | 选择 | 说明 |
|---|---|---|
| 会话创建 | 前端点击“新建会话”调用后端创建 `thread_id` | 新会话按钮会生成一个新的对话框/会话项，避免隐式复用旧 thread |
| 多轮语义 | `messages` + `conversation_summary` + `day_plans` 共同作为上下文 | 不只保存历史，还要让 `clarify` / `dispatch` / `itinerary` / `summarize` 真正读历史 |
| 意图分流 | 新增 `intent` 判断：`plan_new` / `refine_existing` / `qa`；澄清恢复在 API 层拦截，先于 intent | 普通追问与修改上一版行程不应每次全量重跑 |
| 持久化 | LangGraph SQLite checkpointer | MVP 不上用户系统和 Postgres，但会话状态可跨进程重启保存 |
| 前端状态 | 多会话列表 + 当前会话消息流 + 当前会话结果面板 | 切换会话时恢复对应消息、进度、行程、预算和地图状态 |
| 兼容性 | `/api/chat` 保留无 `thread_id` 自动建会话兜底 | 老调用不崩；正式 UI 走 `/api/sessions` 新建 |

## 1. 当前问题

M2-M4 已有 `thread_id`、`interrupt`、`MemorySaver`，所以可以完成“需求澄清式多轮”：

1. 用户输入模糊需求。
2. `clarify` 通过 interrupt 提问。
3. 用户带同一个 `thread_id` 回答。
4. 图从暂停点恢复。

但这不是完整多轮对话，主要缺口是：

- 非 interrupt 的第二轮只用 `{"query": message}` 再跑图，历史消息没有成为 LLM 上下文。
- `dispatch` / `clarify` 只读 `query + clarify_history`，不理解“刚才那个行程”“第二天”“换成便宜点”。
- 上轮 `day_plans` 虽在 state 里，但没有明确的 refine 节点或意图分流使用它。
- `MemorySaver` 是进程内存，后端重启后会话丢失。
- 前端只有一个 `threadId`，没有真正的会话列表和新建会话入口。

M5 的目标是把“会话状态续接”升级为“对话上下文可推理、可修改、可恢复”。

## 2. 用户体验

### 2.1 新建会话

前端左侧新增会话列表，顶部提供“新建会话”按钮。

交互：

1. 用户点击“新建会话”。
2. 前端调用 `POST /api/sessions`。
3. 后端创建新的 `thread_id`，初始化空图状态并写入 SQLite checkpointer。
4. 前端在会话列表新增一个对话框，切换为当前会话，清空消息输入区和右侧结果区。
5. 用户发第一条消息时，`/api/chat` 携带该 `thread_id`。

会话标题策略：

- 新建后默认标题为“新的行程”。
- 第一条用户消息完成后，后端可发 `title` 事件，或前端用首条消息截断生成标题。
- 标题可后续在 M7 用户系统阶段支持手动重命名。

### 2.2 切换会话

用户点击会话列表项：

1. 前端设置 `activeThreadId`。
2. 调用 `GET /api/sessions/{thread_id}` 获取消息快照和最新 `day_plans` / `budget`。
3. 消息区、地图和行程面板恢复到该会话最后状态。

### 2.3 真正多轮示例

支持以下自然语言续轮：

- “第二天太赶了，少安排一个景点。”
- “预算改成 3000，帮我重新压一下。”
- “酒店换成离春熙路近一点的。”
- “刚才那个行程适合带老人吗？”
- “把第一天晚餐换成火锅。”
- “重新规划一个上海的 2 天行程。”

系统行为：

- 修改类请求优先复用已有 `day_plans`，只重排受影响的天或受影响字段。
- 问答类请求不重跑检索和预算，只基于历史行程回答。
- 全新规划请求清理旧行程相关状态，但保留消息历史用于理解用户偏好。

## 3. 后端设计

### 3.1 依赖与 checkpointer

新增依赖：

```bash
uv add langgraph-checkpoint-sqlite aiosqlite
```

配置项：

```python
class Settings(BaseSettings):
    checkpoint_db_path: str = "./data/checkpoints.sqlite"
```

目标实现：

`AsyncSqliteSaver.from_conn_string()` 返回的是 **async context manager**，不是 saver 实例本身——不能像 `checkpointer = AsyncSqliteSaver.from_conn_string(...)` 这样直接拿来构图（会拿到一个 CM 对象，装进 graph 报错）。必须在 FastAPI lifespan 内用 `async with` 持有，连同 graph 一起创建并挂到 `app.state`：

```python
from contextlib import asynccontextmanager
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncSqliteSaver.from_conn_string(settings.checkpoint_db_path) as checkpointer:
        await checkpointer.setup()              # 首次建表
        app.state.graph = build_graph(checkpointer=checkpointer)
        yield
    # 退出 with 时自动关闭 SQLite 连接
```

连带改动（不可省，否则跑不起来）：

- [build_graph()](backend/app/graph/builder.py#L20) 当前**无参数且硬编码 `g.compile(checkpointer=MemorySaver())`**，需改为 `build_graph(checkpointer)` 并把传入的 checkpointer 透传给 `compile`。
- [stream.py](backend/app/graph/stream.py) 当前用**模块级全局 `GRAPH`**（import 期就 compile）。checkpointer 改为 lifespan 内创建后，`GRAPH` 不能再是 import 期全局；`astream_events` / `aget_state` 全部改成从 `request.app.state.graph` 取（chat 路由已持有 `request`，沿调用链传入即可）。

目录约定：

```text
backend/data/checkpoints.sqlite
```

`backend/data/` 加入 `.gitignore`，不提交本地会话数据。

### 3.2 State 扩展

`backend/app/graph/state.py` 新增：

```python
class TripState(TypedDict, total=False):
    query: str
    messages: Annotated[list, add_messages]

    # M5: 多轮上下文
    conversation_summary: str
    last_intent: str               # plan_new/refine_existing/qa
    active_plan_id: str
    refine_request: dict           # 结构化修改指令
    plan_version: int

    # 已有字段继续保留
    clarify_history: Annotated[list, add]
    normalized_req: dict
    day_plans: list
    budget_check: dict
```

字段语义：

- `messages`：完整对话消息，用户和 AI 都写入，供短上下文直接引用。
- `conversation_summary`：当消息超过阈值时压缩出的长期摘要，保留偏好、约束和关键决策。
- `last_intent`：本轮分类结果，供路由使用。
- `refine_request`：对“第几天/哪个 item/怎么改”的结构化解析。
- `plan_version`：每次行程结果变化 +1，前端可用于判断地图/卡片刷新。

### 3.3 记忆压缩阈值

多轮记忆采用“最近消息原文 + 长期摘要 + 结构化行程状态”的组合，不把所有历史消息无限塞进每次 LLM 调用。

**前提：攻略全文不进 `messages`。** `summarize` 写回历史时只存一句简短回执（如“已生成成都 3 天行程，详见行程面板”），完整行程只活在 `day_plans`（前端也从 `day_plans` 渲染）。否则一条 AI 消息就是一整份 1500~3000 tokens 的攻略，recent 窗口瞬间被撑爆、下面的阈值形同虚设。messages 因此保持轻量，主要承载用户自然语言诉求与简短回执。

默认阈值（后端默认模型 `gpt-4o-mini` 128k / `claude-haiku-4-5` 200k，上下文充裕，阈值偏宽以减少有损压缩）：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `RECENT_KEEP_TOKENS` | 4000 tokens | recent 窗口**按 token 预算**保留最近若干轮原文（至少保留最后一轮）；不再按“条数”算，避免一条长消息使窗口失控 |
| `SUMMARY_TRIGGER_TOKENS` | 20000 tokens | recent 窗口之外的旧消息估算超过此值才压缩；模型窗口 128k/200k，没有更早压缩的理由 |
| `SUMMARY_TRIGGER_MESSAGES` | 30 条 | 次要兜底触发：消息数超过 30 条也压缩一次（messages 已轻量，主看 token，本条很少触发）|
| `SUMMARY_TARGET_TOKENS` | 1200 tokens | `conversation_summary` 目标长度；**行程不进摘要**，只存偏好 / 已确认约束 / 否定过的方案 / 未决事项，故 1200 足够 |

触发条件（注意：`messages` 用的是 `add_messages` reducer，**只能追加、不能简单替换**——return 一个短列表只会再追加，要真删除得用 `RemoveMessage`）：

```text
recent = take_recent_until_tokens(messages, RECENT_KEEP_TOKENS)   # 最近若干轮，至少保留最后一轮
old = messages[: len(messages) - len(recent)]
if estimated_tokens(old) > SUMMARY_TRIGGER_TOKENS
   or len(messages) > SUMMARY_TRIGGER_MESSAGES:
    # 压缩 = 生成/更新 conversation_summary，而不是裁剪 state 里的 messages
    conversation_summary = summarize(old, 旧 summary)
```

职责分离（关键，避免和 `add_messages` 搏斗）：

- state 里的 `messages` **永远全量保留**（已是回执级轻量，SQLite 存得下，不折腾 `RemoveMessage`）。
- 压缩只产出 / 更新 `conversation_summary`，由 `memory_update` 节点在每轮 `final` / `answer` 后写回。
- `memory` 节点在**构造本轮 prompt 时**才做窗口选择（`conversation_summary` + recent 窗口原文），绝不去改 state 里的 messages。
- `estimated_tokens` 用 `tiktoken` 或现成估算库，不手写计数。

`day_plans`、`budget_check`、`normalized_req` 这类结构化状态由 checkpointer 原样保存，供后续修改行程使用，压缩流程不碰它们。

摘要必须保留：

- 用户稳定偏好：城市倾向、节奏、饮食、住宿档位、同行人群。
- 已确认约束：天数、预算、日期、人数、交通限制。
- 当前行程关键版本：目的地、每天主题、已被用户明确修改过的点。
- 用户否定过的方案：不想去的景点、不接受的预算/酒店/节奏。
- 未解决事项：仍待澄清的问题或用户要求后续处理的事项。

### 3.4 新增节点

M5 fix 实际落地拓扑（intent + dispatch 物理合并为 dispatch_agent）：澄清恢复（`Command(resume)`）由 API 层在进图前拦截，直接从 interrupt 暂停点（clarify）恢复，**不经过 memory / dispatch_agent**。

```text
（pending interrupt 时：API 层直接 Command(resume=message) 从 clarify 暂停点恢复，跳过 memory / dispatch_agent）

START → memory → dispatch_agent
  ├─ plan_new → reset_plan_new → clarify ⟲ → retrieve → 并行检索(天气/景点/餐饮/交通)
  │             → itinerary → ◇酒店需重排? ─是→ accommodation ─┐
  │                                          └否─────────────────┤→ ◇预算需重算? ─是→ budget ─┐
  │                                                              └否────────────────────────────┤→ summarize
  │             （budget 超支且 plan_new → 回 itinerary 重排）                                    │
  ├─ refine_existing → refine（旧 day_plans 局部重排 + 按 op 选择性补检索）→ 同上「酒店需重排?/预算需重算?」两判断 → summarize
  └─ qa → answer
  → memory_update → END
```

两个判断为**规则路由**（`route_after_plan` / `route_after_accommodation`），依据 `last_intent` + `refine_request.op`，不额外调用 LLM；op→标志映射见实现计划 Global Constraints 表。

节点职责：

| 节点 | 职责 |
|---|---|
| `memory` | 读取 state 中历史消息、摘要、上轮行程；构建本轮上下文窗口 |
| `dispatch_agent` | 判断意图（plan_new / refine_existing / qa）并解析结构化需求；物理合并原 intent + dispatch 两节点 |
| `reset_plan_new` | plan_new 路径专用：清除上轮脏状态（clarified/clarify_round/retry_count/day_plans/budget_check 等），保留 messages/conversation_summary |
| `retrieve` | plan_new 路径的检索锚点，触发 4 个并行检索节点（天气/景点/餐饮/交通） |
| `refine` | 把用户修改请求结构化，并**直接在旧 `day_plans` 上**局部编辑；仅在需要新 POI 时回调对应检索节点，**不走 itinerary 全量重排** |
| `answer` | 不改变行程，只基于历史和当前方案回答用户问题 |
| `memory_update` | 把本轮用户消息、AI 回复、关键行程变化写回 `messages` 和摘要 |

### 3.5 意图分类

`intent` 用 structured output：

```python
class IntentResult(BaseModel):
    intent: Literal["plan_new", "refine_existing", "qa"]
    confidence: float
    reason: str
    target_day: int | None = None
    needs_full_replan: bool = False
```

分类规则：

- `plan_new`：用户明确换城市/换目的地/重新做一个行程，或当前没有 `day_plans`。
- `refine_existing`：用户提到“第二天”“刚才”“换/删/加/改预算/改酒店/轻松一点”等，并且 state 中已有 `day_plans`。
- `qa`：用户只询问解释、建议、适合不适合，不要求改变方案。

若置信度低：

- 有明显缺口时进入 `clarify` 提问。
- 否则默认 `qa`，避免误改用户行程。

**省钱短路**：当 state 中没有 `day_plans`（首轮）时，直接判定 `plan_new`，跳过 intent 的 LLM 调用。`memory` 节点只做上下文窗口拼装，**不需要 LLM**；每轮额外的 LLM 往返只有 `intent` 这一次，且可被本短路省掉。

**plan_new 进入时必须重置的脏状态**：checkpointer 会把整个 state 持久化，同一 `thread_id` 内上一轮的标志会残留到下一轮。当用户在已有行程的会话里说“重新做上海 2 天”（intent=plan_new）时，若不重置，[route_after_clarify](backend/app/graph/builder.py#L65) 看到上轮的 `clarified=True` 会**直接跳过澄清**，`retry_count` 也会从旧值继续累加。`plan_new` 路由进 clarify 前必须显式重置以下字段（保留 `messages` / `conversation_summary` 以延续偏好）：

```python
{
    "clarified": False,
    "clarify_round": 0,
    "retry_count": 0,
    "day_plans": [],
    "budget_check": {},
    "daily_centers": [],
    # 旧城市的 attractions/restaurants/weather/transport 会被新一轮检索覆盖，无需手动清
}
```

### 3.6 节点上下文改造

`clarify` 输入从：

```text
原始需求：query
已澄清：clarify_history
```

升级为：

```text
当前用户消息：query
会话摘要：conversation_summary
最近消息：messages[-8:]
当前结构化需求：normalized_req
已澄清：clarify_history
```

`dispatch` 输入加入历史偏好：

```text
请综合当前用户消息、会话摘要和已澄清答案，输出本轮最新结构化旅行需求。
当用户没有重提某字段时，可继承历史偏好；当用户明确修改时，以最新消息为准。
```

`itinerary` **仅服务 plan_new 全量编排**，保持现状（`cluster_by_day` 聚类 + LLM 编排），不接收 `refine_request`。

> 注意：`itinerary` 天然是"从检索结果重建"，把它复用到局部修改会退化成全量重排，违背"只改受影响的天"，也会让 `test_multiturn_refine` 的 `changed_days=[2]` 断言挂掉。局部修改的逻辑全部放在 `refine` 节点（见 3.7），**refine 路径不回到 itinerary**。

`summarize` 输入加入本轮类型：

- 新规划：输出完整攻略。
- 修改方案：先说明已修改内容，再输出更新后的相关天和关键总览。
- 问答：只回答问题，不重复整份攻略。

**写回 messages 的方式**（配合 3.3，避免 token 膨胀）：summarize 流式生成的完整攻略照常通过 `token` / `final` SSE 推给前端展示；但写回 `state.messages` 的 `AIMessage` **只存简短回执**（如“已生成成都 3 天行程，详见行程面板”），不存攻略全文——全文由 `day_plans` 承载。当前 [summarize.py](backend/app/graph/nodes/summarize.py) 是把完整 `text` 作为 `AIMessage` 追加（[summarize.py:26](backend/app/graph/nodes/summarize.py#L26)），需改成回执。

> 副作用（可接受）：实时对话里这条助手气泡是完整攻略，但刷新 / 切回会话后从 `state.messages` 恢复时只显示回执，完整行程由右侧 `day_plans` 面板呈现。MVP 接受这种“聊天区简短、面板区完整”的呈现差异。

### 3.7 refine 节点

`refine` 负责把自然语言修改变成结构化操作。

```python
class RefineRequest(BaseModel):
    op: Literal["add", "remove", "replace", "relax", "tighten", "change_budget", "change_hotel", "change_meal", "reorder"]
    target_day: int | None = None
    target_item_name: str | None = None
    constraints: dict = Field(default_factory=dict)
    needs_search: bool = False
    needs_budget_recheck: bool = True
```

执行策略（**refine 局部重排在 refine 节点内完成，只改受影响天**；其后接 `route_after_plan` 两段按需判断：`change_hotel` 才走 accommodation、`needs_budget_recheck` 才走 budget、`reorder` 直达 summarize；**绝不回到 itinerary 全量重排**）：

- `remove` / `relax` / `reorder`：纯算法 + 轻量 LLM 在旧 `day_plans` 上删减 / 调整顺序，不调检索；直接通过 `route_after_plan` 跳到 summarize。
- `replace` / `add`：需要新 POI 时调用对应检索节点（`attractions` / `restaurants`）补候选，再局部插入 / 替换受影响的项；`needs_budget_recheck=True` 时经 `route_after_plan` 走 budget。
- `change_meal`：触发 `restaurants` 检索补候选后局部替换餐饮项；其后经 `route_after_plan` 按需走 budget。
- `change_budget`：更新预算上限后经 `route_after_plan` 进入 `budget` 节点核算；若超支，用 `budget_advice` 在 refine 内对受影响项局部压成本（删 / 降档），而不是触发 plan_new 的 itinerary 回退循环。
- `change_hotel`：`change_hotel` 标志使 `route_after_plan` 路由到 `accommodation` 重排，再经 `route_after_accommodation` 按需走 budget。
- 影响范围不明确时，先走 `clarify`，问”你想调整第几天？”

### 3.8 API 设计

新增会话接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/sessions` | 创建新会话，返回 `thread_id` |
| `GET` | `/api/sessions` | 列出本地匿名会话 |
| `GET` | `/api/sessions/{thread_id}` | 获取会话快照：消息、day_plans、budget、标题 |
| `DELETE` | `/api/sessions/{thread_id}` | 删除会话及其本地元数据；checkpoint 清理可先软删除 |

`POST /api/chat` 请求：

```json
{
  "message": "第二天太赶了，少一个景点",
  "thread_id": "abc123"
}
```

兼容策略：

- `thread_id` 为空：后端创建新会话并先发 `session` 事件。
- `thread_id` 不存在：**存在性以 `session_meta` 查表为准**——`aget_state` 对没见过的 thread 返回空快照（`values={}`）而非报错，会被当成 plan_new 静默新建。必须先查 `session_meta`，查不到（或已软删除）才返回 `error`，提示会话不存在或已删除。
- 存在 pending interrupt：优先 `Command(resume=message)`，从 clarify 暂停点恢复，不进 memory / intent。

新增/扩展 SSE 事件：

| event | payload | 说明 |
|---|---|---|
| `session` | `{"thread_id":"..."}` | 新会话 id |
| `title` | `{"thread_id":"...","title":"成都 3 天游"}` | 会话标题更新 |
| `intent` | `{"intent":"refine_existing"}` | 可选，用于前端调试或进度展示 |
| `plan_patch` | `{"plan_version":2,"changed_days":[2]}` | 可选，局部更新提示 |
| `final` | `{"answer":"...","day_plans":[...],"budget":{...},"plan_version":2}` | 最终结果 |

## 4. 前端设计

### 4.1 布局

左侧从单一聊天区升级为：

```text
┌────────────────────────────┐
│ + 新建会话                  │
│ 成都三日游                  │
│ 上海周末游                  │
│ 新的行程                    │
├────────────────────────────┤
│ 当前会话消息流              │
│ Agent 进度                  │
│ 输入框                      │
└────────────────────────────┘
```

也可以保持现有左栏宽度，在顶部栏放“新建会话”，左侧消息区上方显示会话下拉。M5 推荐先做窄会话列表，信息架构更清楚。

### 4.2 Store 结构

`frontend/src/stores/trip.ts` 改为多会话：

```ts
export interface Conversation {
  threadId: string
  title: string
  messages: Message[]
  dayPlans: DayPlan[]
  budget: Budget | null
  activeDay: number | null
  activePoiId: string | null
  planVersion: number
  updatedAt: string
}

const conversations = ref<Conversation[]>([])
const activeThreadId = ref<string | null>(null)
const activeConversation = computed(() => conversations.value.find(c => c.threadId === activeThreadId.value) ?? null)
```

现有 `messages`、`threadId`、`dayPlans`、`budget` 从全局单值迁移到当前 `Conversation` 内。

### 4.3 新建会话动作

```ts
async function createConversation() {
  const session = await createSession()
  conversations.value.unshift({
    threadId: session.thread_id,
    title: '新的行程',
    messages: [],
    dayPlans: [],
    budget: null,
    activeDay: null,
    activePoiId: null,
    planVersion: 0,
    updatedAt: new Date().toISOString(),
  })
  activeThreadId.value = session.thread_id
}
```

发送消息时必须使用 `activeThreadId`。如果没有当前会话，自动先创建一个。

### 4.4 恢复与刷新

MVP 可采用：

- 前端启动时调用 `GET /api/sessions`，恢复会话列表。
- `activeThreadId` 存 localStorage，刷新后优先恢复"上次查看的会话"；该会话不存在时再回退到最近更新的会话。
- 切换会话时调用 `GET /api/sessions/{thread_id}` 拉最新快照。

后端需要维护轻量 `session_meta` 表，因为 LangGraph checkpoint 适合恢复图状态，但不适合直接作为会话列表查询模型。

## 5. SQLite 数据

SQLite 分两类表：

1. LangGraph checkpointer 自己维护的 checkpoint 表。
2. 应用层维护的会话元数据表。

建议新增 `session_meta`：

```sql
CREATE TABLE IF NOT EXISTS session_meta (
  thread_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT
);
```

消息和行程主体优先从 checkpoint state 快照读取。若后续需要更高效的列表预览，再加 `last_message`、`plan_summary` 字段。

`session_meta` 的维护时机（不补会导致会话列表"最近更新排序"一直停在创建时间）：

- `POST /api/sessions`：插入一行，`title` 默认"新的行程"，`created_at` / `updated_at` 写当前时间。
- 每轮聊天结束（`memory_update` 后）：更新 `updated_at`；首条用户消息完成后回写 `title`（同时发 `title` SSE 事件）。
- `DELETE /api/sessions/{thread_id}`：写 `deleted_at` 软删除；checkpoint 可后续用 LangGraph 的 `adelete_thread(thread_id)` 物理清理。
- 列表 / 详情查询都需带 `deleted_at IS NULL` 过滤。

## 6. 测试与验收

### 后端测试

- `test_sessions.py`：创建会话、列表出现、详情可读、删除后不可继续聊天。
- `test_sqlite_checkpointer.py`：同一 `thread_id` 的状态写入后，重建 graph 仍可读取。
- `test_multiturn_refine.py`：先生成 `day_plans`，再发“第二天少一个景点”，断言不是空白重规划，且 `changed_days=[2]`。
- `test_multiturn_qa.py`：已有行程后问“适合带老人吗”，断言不触发检索节点，不修改 `day_plans`。
- `test_multiturn_replan.py`：已有成都行程后说“重新做上海 2 天”，断言 `normalized_req.city=上海` 且旧成都 day_plans 被替换。
- `test_clarify_resume_still_works.py`：pending interrupt 时带 `thread_id` 回答，仍走 `Command(resume=...)`。

### 前端验证

- `bun run build` 类型通过。
- 新建两个会话，分别发不同城市需求，切换后消息和地图不串。
- 刷新页面后会话列表仍存在。
- 后端重启后，旧 `thread_id` 可继续追问。

### 手动验收脚本

1. 点击“新建会话”，输入“成都 3 天 2 人，预算 4000，喜欢历史和美食”。
2. 生成后输入“第二天太赶了，少安排一个景点”。
3. 观察只更新第二天或明确说明影响范围，地图 marker 同步更新。
4. 输入“预算改成 3000”。
5. 观察预算核算和必要重排执行，最终 `budget.retry_count` 正常。
6. 点击“新建会话”，输入“上海周末亲子游”。
7. 切回成都会话，输入“刚才那个酒店离地铁近吗？”系统能基于成都方案回答。
8. 重启后端，刷新前端，继续成都会话，历史仍可用。

## 7. 不在本轮范围

- 用户登录、云端同步、多设备共享。
- 会话分享链接。
- Postgres / Redis 部署化存储。
- 复杂可视化 diff。M5 只需说明更新了哪些天，并刷新最终 `day_plans`。
- 完整版本回滚。`plan_version` 只标识版本，不提供历史版本切换。

## 8. 实施顺序

1. 后端引入 SQLite checkpointer 和 `session_meta`，补会话 API（含 `build_graph` 改签名、`GRAPH` 挪到 `app.state`）。
2. **先做 refine 最小 spike**（最高风险，提前验证核心卖点）：在现有图上临时加 `intent` + `refine`，跑通"先生成成都行程，再说'第二天少一个景点'真能只改第二天、`changed_days=[2]`"。打通后再铺开其余工作，避免最后才发现局部修改做不出来。
3. 扩展 State：`conversation_summary`、`last_intent`、`refine_request`、`plan_version`，并落实 plan_new 的脏状态重置。
4. 前端 store 从单会话迁移到多会话，新增“新建会话”和会话列表。
5. 补齐 `answer` / `memory_update` 节点与记忆压缩，接入完整图路由。
6. 改造 `clarify` / `dispatch` / `summarize` prompt，让历史真正参与推理。
7. 增加测试：session、SQLite 恢复、多轮 refine、QA、不串会话。
8. 手动验收多会话切换、刷新恢复、后端重启恢复。
