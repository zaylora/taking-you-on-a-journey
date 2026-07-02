# 历史会话栏显示隐藏按钮

## 任务目标

按截图调整 `frontend-next` 聊天页顶部按钮：三横线按钮用于显示/隐藏左侧历史会话栏，删除模型选择器左侧多余的顶部 `+` 新建按钮。左侧历史栏标题旁的 `+` 仍保留为新建会话入口。

## 改动文件清单

| 文件 | 说明 |
| --- | --- |
| `frontend-next/src/components/chat-panel.tsx` | 将顶部三横线按钮接入历史栏显隐回调，并删除顶部多余的新建会话按钮。 |
| `frontend-next/src/components/trip-chat-app.tsx` | 增加历史会话栏开关状态，按状态渲染左侧 `SessionSidebar`。 |
| `frontend-next/src/components/chat-panel.test.tsx` | 增加顶部按钮行为测试，断言三横线触发历史栏切换且聊天顶部不再渲染新建会话按钮。 |
| `frontend-next/src/components/trip-chat-app.test.tsx` | 增加整页交互测试，断言点击三横线可隐藏并恢复历史会话栏。 |
| `docs/README.md` | 增加本次改动记录索引。 |

## 改动详情

- `ChatPanel` 新增 `onToggleHistorySidebar` 回调，只由三横线按钮触发。
- 三横线按钮的可访问名称改为「显示隐藏历史会话」，让按钮职责和截图标注一致。
- 删除聊天顶部模型选择器左侧的 `+`，避免和左侧历史栏里的新建入口重复。
- `TripChatApp` 使用 `historySidebarOpen` 控制 `SessionSidebar` 是否渲染。

## 测试结果

| 阶段 | 命令 | 结果 |
| --- | --- | --- |
| RED | `bun run test src/components/chat-panel.test.tsx src/components/trip-chat-app.test.tsx` | 失败 2 个测试，确认当前没有「显示隐藏历史会话」按钮且顶部仍有多余新建按钮。 |
| GREEN | `bun run test src/components/chat-panel.test.tsx src/components/trip-chat-app.test.tsx` | 通过，2 个测试文件、12 个测试通过。 |
| 回归 | `bun run test --run` | 通过，7 个测试文件、23 个测试通过。 |
| 构建 | `bun run build` | 通过，Next.js 生产构建和 TypeScript 检查通过。 |

## 相关讨论

- 本次按截图做最小改动，只调整历史栏显隐和重复按钮，不改变新建会话、模型选择、导出和登录的其他行为。
- 隐藏历史栏后仍可通过顶部三横线恢复；新建会话入口只保留在历史栏内。
