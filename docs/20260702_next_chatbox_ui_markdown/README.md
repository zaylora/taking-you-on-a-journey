# Next Chatbox UI Markdown 改动记录

## 任务目标

将 `frontend-next` 的聊天框改成 `https://chatbot.ai-sdk.dev/docs` 视频中 Vercel AI Chatbot 风格的暗色 UI，并补齐多消息会话请求历史与 Markdown 渲染。

## 改动文件清单

| 文件 | 说明 |
| --- | --- |
| `frontend-next/src/components/chat-panel.tsx` | 重做顶部工具栏、消息区、浮动输入框；助手消息改为 Markdown 渲染。 |
| `frontend-next/src/components/chat-panel.test.tsx` | 新增 Markdown DOM 和多消息展示测试。 |
| `frontend-next/src/components/trip-chat-app.tsx` | 发送消息时带上当前可见会话历史。 |
| `frontend-next/src/components/trip-chat-app.test.tsx` | 覆盖多轮历史随下一次请求发送。 |
| `frontend-next/src/lib/sse.ts` | `fetchTripChatStream` 增加可选 `messages` 字段序列化。 |
| `frontend-next/src/lib/sse.test.ts` | 覆盖请求体中的历史消息。 |
| `frontend-next/src/app/globals.css` | 增加聊天 Markdown 样式。 |
| `frontend-next/src/test/setup.ts` | 测试后自动 cleanup，避免 DOM 泄漏。 |
| `frontend-next/package.json` / `frontend-next/bun.lock` | 新增 `react-markdown`、`remark-gfm` 依赖。 |
| `docs/superpowers/specs/2026-07-01-next-chatbox-ui-markdown-design.md` | 设计说明。 |
| `docs/superpowers/plans/2026-07-01-next-chatbox-ui-markdown.md` | 实现计划。 |

## 改动详情

- UI 参考 Vercel AI Chatbot 视频：暗色全屏、紧凑顶部工具栏、居中欢迎态、底部半透明浮动输入框。
- 助手消息使用 `react-markdown` + `remark-gfm` 渲染标题、粗体、列表和链接；用户消息仍按纯文本显示。
- 请求仍保留原有 `message`、`thread_id` 字段，同时新增兼容性的 `messages` 字段，序列化当前可见会话历史，便于后端后续消费。
- 现有 LangGraph `thread_id` 会话记忆、SSE 流式事件、右侧行程 Artifact/地图逻辑保持不变。

## 测试结果

| 命令 | 结果 |
| --- | --- |
| `bun run test` | 5 files / 10 tests passed |
| `bun run lint` | passed |
| `bun run build` | passed |
| Playwright production snapshot | `http://127.0.0.1:3101/` 页面渲染正常，无应用控制台错误 |

## 相关讨论

- Markdown 解析遵循依赖优先原则，未手写解析器。
- “多消息会话”前端侧实现为请求历史随下一轮发送；真实上下文仍由后端 `thread_id` 和 LangGraph checkpointer 负责，避免破坏现有接口。
- 视觉检查时发现已有 dev server 占用 `3000`，Next 不允许同项目同时启动第二个 dev server；最终用 production server `3101` 完成无 HMR 噪音的截图验证。

