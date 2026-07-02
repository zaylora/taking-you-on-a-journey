# 聊天区滚动条与输入框布局对齐官网

## 任务目标

针对 `frontend-next` 聊天页提出三点：

1. 确认 AI Elements 的 `Reasoning`（推理过程折叠）是否已接入，未接入则补上。
2. 将聊天区滚动条改成与官网 [AI Elements docs](https://elements.ai-sdk.dev/docs) 的 ChatGPT 示例一致。
3. 修复「聊天区域遮挡下方输入框」的问题。

## 结论概览

- **需求 1：已满足，无需改动。** `chat-panel.tsx` 已完整使用 `Reasoning / ReasoningTrigger / ReasoningContent`：assistant 消息中除最后一段文本外的中间文本片段被渲染为可折叠的推理块，流式时显示「正在推理」，结束后折叠为「已思考 N 秒」，符合 `AGENTS.md` 对中间推理文本的约定。
- **需求 2、3 同源。** 二者由同一处布局 hack 引起，一并修复。

## 根因分析

`chat-panel.tsx` 原本把输入框做成「悬浮覆盖」式：

```
对话区  <div class="relative min-h-0 flex-1">      // flex-1 撑满到 section 底部
输入框  <div class="sticky bottom-0 z-10 -mt-28 pointer-events-none">  // 用负 margin 浮在对话区之上
```

配合 `ConversationContent` 的 `pb-40` 预留空白。由此产生两个现象：

1. 对话滚动区 `flex-1` 一直延伸到窗口底部（输入框只是用 `-mt-28` 浮在其上），**滚动条随之贯穿到窗口最底部、穿过输入框背后**，与官网「滚动条止于输入框上沿」不一致。
2. 对话区与输入框的上下关系全靠 `z-index` + `pointer-events` 维持，脆弱且视觉混乱，即为「聊天区域挡住输入框」。

官网 ChatGPT 示例实为标准的 **flex 两段式**（经浏览器实测其 DOM 确认）：根容器 `flex flex-col overflow-hidden` → 对话区 `flex-1`（内部由 `use-stick-to-bottom` 滚动）→ 输入框 `shrink-0` 位于正常流底部，不悬浮、不覆盖。

此外，`use-stick-to-bottom` 的真正滚动容器是其内部 `StickToBottom.Content`（inline `overflow:auto`），本地与官网该容器 CSS 完全一致。滚动条呈**白色**而非官网的深色，是因为全局 `color-scheme` 为 `normal`（浅色）——`.dark` class 只切换 CSS 变量，不改变原生滚动条配色。

## 改动文件清单

| 文件 | 改动 |
| --- | --- |
| `frontend-next/src/components/ai-elements/conversation.tsx` | 外层 `StickToBottom` 的 `overflow-y-hidden` 恢复为官方默认 `overflow-y-auto`。 |
| `frontend-next/src/components/chat-panel.tsx` | 输入框容器由 `pointer-events-none sticky bottom-0 z-10 -mt-28 px-4 pb-5` 改为 `shrink-0 px-4 pb-5`；`PromptInput` 去掉 `pointer-events-auto`；`ConversationContent` 的底部留白 `pb-40` 改为 `pb-6`。 |
| `frontend-next/src/app/globals.css` | `.dark` 规则新增 `color-scheme: dark;`，使深色区域的原生滚动条渲染为深色（shadcn 官方约定）。 |

## 改动详情

- **布局改两段式**：输入框改为 `shrink-0` 后位于 `section`（`flex flex-col`）正常流底部，对话区 `flex-1` 自然止于输入框上沿；上下排布不再重叠，无需 `z-index`/`pointer-events` hack。滚动条随对话区一起止于输入框上沿，与官网一致。
- **去掉 `pb-40`**：该大留白仅为悬浮输入框预留，两段式下不再需要，改为常规 `pb-6`。
- **`overflow-y-auto`**：恢复被改动过的 AI Elements 组件默认值，语义与官网一致；因内层 `Content` 才是实际滚动层，外层不会产生第二条滚动条（已实测无双滚动条）。
- **`color-scheme: dark`**：`color-scheme` 为继承属性，`.dark` 容器设置后其后代滚动容器继承，原生滚动条由白色变为深色细条，融入暗色背景。

## 测试结果

- `bunx tsc --noEmit`：无类型错误。
- `bunx vitest run`：5 个测试文件、15 个用例全部通过。
- 浏览器实测（注入 6 轮长对话复现 → 修复后回归）：
  - 滚动条为深色细条，止于输入框上沿，不再贯穿窗口底部；
  - 输入框固定在底部，不被对话区遮挡；
  - `Reasoning`「已思考」折叠、`Tool` 完成态、空状态与短对话布局均正常。

## 相关讨论

- 复现长对话时临时修改了 `src/app/page.tsx` 注入假消息，验证后已还原为 `<TripChatApp />`。
- 方案选择「flex 两段式」而非继续用悬浮 hack，因官网 ChatGPT 示例本身就是两段式，最贴合用户「跟官网一致」的诉求，且最稳、改动最小。
