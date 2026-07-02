# 移除正在生成文案与双滚动条修复

## 任务目标

1. 去掉 `frontend-next` 前端聊天区显示的「正在生成」。
2. 修复聊天页出现两个纵向滚动条的问题。

## 改动文件清单

| 文件 | 改动 |
| --- | --- |
| `frontend-next/src/components/chat-panel.tsx` | 删除 loading 兜底状态中的「正在生成」渲染，只保留真实节点进度与工具/推理状态。 |
| `frontend-next/src/components/ai-elements/conversation.tsx` | 将 `Conversation` 外层从 `overflow-y-auto` 改为 `overflow-y-hidden`，避免它与 `use-stick-to-bottom` 内部滚动层同时显示滚动条。 |
| `frontend-next/src/components/chat-panel.test.tsx` | 新增/更新断言：loading 时不出现「正在生成」；`Conversation` 外层不作为第二滚动容器。 |

## 改动详情

- 「正在生成」来自 `ChatPanel` 的 `showLoading` 兜底渲染：当没有 `activeNodeLabel`、也没有正在展示的推理或工具状态时，会额外渲染一行通用 loading 文案。本次按要求删除该兜底，只保留已有的「正在思考...」「正在推理」「运行中」等具体状态。
- 双滚动条根因在 `Conversation` 外层和 `use-stick-to-bottom` 内层都具备滚动能力。源码确认 `StickToBottom.Content` 会创建实际滚动层，并在需要时把内部 `scrollRef` 的 `overflow` 设为 `auto`；外层再使用 `overflow-y-auto` 时会形成两个纵向滚动容器。本次将外层改回 `overflow-y-hidden`，让内部滚动层独占滚动条。

## 测试结果

- `bun run test --run src/components/chat-panel.test.tsx`：6 个用例通过。
- `bun run test --run`：5 个测试文件、16 个用例通过。
- `bun run build`：通过，Next.js 16.2.9 生产构建成功。

## 相关讨论

- 未改动请求、停止生成、SSE 或消息状态逻辑；本次仅处理可见文案和滚动容器归属。
- 之前的滚动条布局记录中曾把外层恢复为 `overflow-y-auto`；本次根据实际截图和 `use-stick-to-bottom` 源码确认，该外层会与内部滚动层叠加，因此改为隐藏外层溢出。
