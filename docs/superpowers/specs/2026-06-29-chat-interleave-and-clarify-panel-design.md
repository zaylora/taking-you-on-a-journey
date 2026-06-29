# 聊天交错渲染 + 澄清浮层面板 设计文档

日期：2026-06-29

## 背景

当前对话区有两处体验问题：

1. **工具调用与 LLM 文本分离**：一条 assistant 消息把所有文本拼进 `content: string`，
   所有工具调用堆进 `toolSteps: []` 并统一渲染在正文顶部（`AgentProgress`）。
   结果是「一坨工具链 + 一坨正文」，无法呈现 codex 那种
   `文本 → 工具 → 文本 → 工具` 的交错过程。

2. **澄清交互简陋**：澄清问题作为普通 assistant 消息显示在消息流里，选项是气泡内的
   按钮（`MessageList.vue` 的 `clarify-options`）。缺少自定义填写入口；选过的澄清会在
   历史里留下一排悬空按钮。

本设计解决这两点。

## 目标

- 对话消息按**到达顺序**交错渲染文本片段与工具片段（codex 风格）。
- 区分「中间推理」与「最终回复」：中间推理淡色、输出时展开、输出完自动折叠为「已思考」
  一行（可点击重新展开）；最终回复黑色、始终展开。
- 澄清改为输入框上方**从下往上弹出的浮层面板**，含选项按钮 + 自定义填写框；
  选择或提交后面板关闭、恢复输入框。

## 非目标

- 不改后端 ReAct 编排逻辑、不改澄清 interrupt/恢复机制。
- 不改地图、行程卡片、预算等结果区。

---

## 需求 2：文本与工具交错渲染（方案 A）

### 数据结构改造

把一条 assistant 消息从 `content + toolSteps` 改造为**有序片段列表** `segments`。

```ts
// types / stores/trip.ts
export type Segment =
  | { kind: 'text'; text: string; role: 'reasoning' | 'answer' }
  | { kind: 'tool'; tool: string; label: string; status: 'running' | 'done' }

export interface Message {
  role: 'user' | 'assistant'
  segments: Segment[]          // 取代 content + toolSteps
  kind?: 'text' | 'error'
  // content 字段保留给 user 消息与 error 消息（纯文本），assistant 一律走 segments
}
```

说明：
- user 消息、error 消息内容简单，仍可用单个 text segment 表达，统一走 segments，
  避免两套渲染路径。
- `role: 'reasoning' | 'answer'` 不在流式过程中就固定，而是**渲染时**根据「是否为最后一个
  text 段」动态判定（见下）。流式构建时一律先记为文本，渲染层决定样式。

### 前端片段构建（store）

在 `stores/trip.ts` 增加面向 segments 的操作，替换 `appendToLastMessage` /
`startToolCall` / `endToolCall`：

- **`appendToken(text)`**：取当前 assistant 占位消息；若 `segments` 末尾是 text 段则
  追加文本，否则 push 一个新的 text 段（工具调用天然成为文本分界）。
- **`startToolCall(tool, label)`**：把末尾仍在 running 的 tool 段收尾为 done（ReAct 串行），
  push 一个 `{ kind:'tool', status:'running' }` 段。
- **`endToolCall(tool)`**：从尾部找最近一个同名 running tool 段标记 done。

`ensureAssistantMessage` 逻辑不变（最后一条是 assistant 则复用，否则新建空 segments 消息）。

### 中间推理 vs 最终回复的判定

**前端纯渲染期判定，无需后端新事件。** ReAct 的最终回复永远是消息里最后一个 text 段：

- `segments` 中**最后一个** `kind==='text'` 段 → `answer`（黑色、常展开）。
- 其余 text 段 → `reasoning`（淡色）。

> 后端无需区分 token 来源：`on_chat_model_stream` 已对所有 model 调用流出 token，
> 中间推理本就在流里。只是过去前端把它们全拼成一段、看不出层次。

### 展开/折叠状态

reasoning 段：
- **正在写入的那一段**（即「当前 segments 末尾且是 text、且 loading 中」）→ 展开，实时显示思考流。
- **已写完的 reasoning 段**（后面已经来了新片段，说明它封口了）→ 自动折叠为一行
  「已思考」，点击切换展开/折叠。折叠态由组件本地 `ref<Set<number>>` 记录手动展开的索引。
- 历史回放的 reasoning 段：默认折叠。

### 渲染（MessageList.vue）

assistant 消息体改为遍历 `segments` 顺序渲染：

```
v-for segment in msg.segments:
  - kind==='tool'  → 渲染一个工具 pill（沿用 AgentProgress 的 pill 样式，
                     可保留 AgentProgress 组件但改为「渲染单个 tool 段」或内联）
  - kind==='text' & role==='reasoning' → 淡色推理块，含折叠/展开逻辑
  - kind==='text' & role==='answer'    → 黑色 markdown 正文（renderMarkdown）
```

`AgentProgress` 从「渲染整条工具链」退化为「渲染单个 tool pill」（或直接把 pill 模板内联进
MessageList 的 segment 循环）。pill 的 slide-fade 动画保留。

`inlineThinking` / `showStandaloneThinking`（首工具/正文到达前的瞬态思考气泡）逻辑保留，
判据从「toolSteps 有无 running」改为「segments 末尾 tool 段是否 running」。

### 历史回放（后端 message_history.py）

`aggregate_messages` 当前产出 `{content, tool_steps}`。改为产出 `segments`，保持顺序：
遍历一个用户回合内的 AIMessage 序列，按出现顺序把 AIMessage 的文本块与其 tool_calls
交错 push 进 segments。`tool_steps()` 复用 `build_tool_label`。

`reconstruct_messages_from_history` / `messages_with_xhs_sources` 相应改为操作 segments
（笔记来源 md 追加到最后一个 answer text 段）。

前端 `applySnapshot` 把后端 `segments` 映射进 `Message.segments`，tool 段 status 一律 done。

> SessionSnapshot 的消息结构（`types/index.ts`）同步改为 segments。

### 安全约定变更

AGENTS.md「中间节点的 LLM token 不暴露给前端，仅最终回复逐字流出」一条与本设计冲突。
本设计**经用户确认**改为：中间推理文本随 token 事件流出前端，淡色展示、写完折叠。
需更新 AGENTS.md 该条与「SSE 事件契约」说明。`error` 事件脱敏约定不变。

---

## 需求 1：澄清浮层面板

### 现状

澄清问题作为 assistant 消息进消息流，选项在气泡内（`MessageList.vue`），选完按钮悬空遗留，
无自定义填写。

### 改造

- 新增 **`ClarifyPanel.vue`**：浮层面板，绝对定位在 `ChatInput` 上方，从下往上滑入。包含：
  - 澄清问题文字（`question`）。
  - 选项按钮（`options`），点击即把该选项作为答案发出。
  - 一个自定义输入框 + 提交按钮，让用户填官方选项之外的答案。
  - 可选关闭按钮（不答直接关，面板消失但澄清消息仍在流里）。
- **store** 增 `pendingClarify: ClarifyPayload | null`。
- **useSSE** 收到 `clarify` 事件：除现有 `addClarifyMessage`（保留问题进消息流，用于历史完整）
  外，设置 `pendingClarify`；`loading=false`。发送答案（选项或自定义）时复用现有 `send`，
  并清空 `pendingClarify`，面板滑下关闭。
- **MessageList.vue**：移除气泡内 `clarify-options` 渲染（选项只在浮层出现），
  避免历史里悬空按钮。assistant 澄清消息只显示问题文字。
- **ChatPanel.vue**：在 `ChatInput` 上方挂 `ClarifyPanel`，`v-if="tripStore.pendingClarify"`。

### 数据契约

`ClarifyPayload`（`field`/`question`/`options`）已足够。自定义填写内容直接当普通消息发出，
后端澄清恢复逻辑（interrupt resume）无需改动。

---

## 改动文件清单

| 文件 | 改动 |
| --- | --- |
| `frontend/src/types/index.ts` | 新增 `Segment` 类型；`SessionSnapshot.messages` 改 segments |
| `frontend/src/stores/trip.ts` | `Message.segments`；`appendToken`/`startToolCall`/`endToolCall` 改造；`pendingClarify` 状态 |
| `frontend/src/composables/useSSE.ts` | token/tool 事件走 segments；clarify 设置 pendingClarify |
| `frontend/src/components/MessageList.vue` | 按 segments 顺序渲染；reasoning 折叠；移除气泡内选项 |
| `frontend/src/components/AgentProgress.vue` | 退化为单 tool pill 渲染（或内联） |
| `frontend/src/components/ClarifyPanel.vue` | **新增** 浮层澄清面板 |
| `frontend/src/components/ChatPanel.vue` | 挂载 ClarifyPanel |
| `backend/app/services/message_history.py` | `aggregate_messages` 等产出 segments |
| `backend/tests/...` | 历史回放 segments 单测；reducer/纯函数边界 |
| `AGENTS.md` | 更新 token 暴露约定 + SSE 契约说明 |

## 测试

- **后端**：`message_history` 的 segments 重建针对 ReAct 多轮工具+文本交错、笔记来源追加、
  压缩历史回放等边界补 pytest，对 LLM/高德打桩。
- **前端**：`bun run build`（vue-tsc）全绿；手动验证流式交错、reasoning 折叠、
  澄清面板弹出/选择/自定义提交/关闭。

## 关键设计决策

1. **中间推理与最终回复在前端渲染期判定**（最后一个 text 段=回复），不引入后端新事件，
   契约最小化。
2. **方案 A（segments 取代 content+toolSteps）** 而非给 toolStep 记插入位置的 hack 方案：
   结构清晰、交错天然、易支持淡色/折叠。
3. **澄清问题仍留在消息流**（历史完整），选项**移出气泡**只在浮层，避免悬空按钮。
4. 自定义澄清答案走普通消息通道，**后端零改动**。
