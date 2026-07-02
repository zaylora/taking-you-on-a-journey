# frontend-next 历史会话恢复与左侧列表

## 任务目标

修复 `frontend-next` 启动后没有历史会话记录的问题：页面应从后端 `/api/sessions` 恢复会话列表，加载最近会话详情，并把历史会话放在左侧。

## 改动文件清单

| 文件 | 说明 |
| --- | --- |
| `frontend-next/src/lib/sessions.ts` | 新增 session API 封装，并把后端快照转换为前端 `TripUiState` 局部状态。 |
| `frontend-next/src/lib/types.ts` | 补充 `SessionListItem`、`SessionSnapshot`、`SessionMessage`、`SessionSegment` 类型。 |
| `frontend-next/src/components/trip-chat-app.tsx` | 启动时加载会话列表和最近会话；新增左侧历史会话栏；支持新建和切换历史会话。 |
| `frontend-next/src/components/chat-panel.tsx` | 保留聊天区新建会话按钮回调，不再在顶部展示历史条。 |
| `frontend-next/src/components/trip-chat-app.test.tsx` | 增加历史会话恢复回归测试，断言历史导航位于左侧 `aside` 中。 |

## 改动详情

- 新增 `listSessions`、`getSession`、`createSession` 客户端封装，统一使用 `NEXT_PUBLIC_API_BASE` 或默认 `http://localhost:8000`。
- `TripChatApp` 在没有传入 `initialState` 时自动请求 `/api/sessions`，并加载最近一条会话快照恢复消息、行程、预算和版本号。
- 新增左侧 `SessionSidebar`，历史会话列表在 `aside` 中垂直展示；生成中禁用新建和切换，避免流式状态被切走。
- 流式聊天结束后刷新会话列表，让后端生成的新标题能回到左侧历史栏。

## 测试结果

| 命令 | 结果 |
| --- | --- |
| `bun run test src/components/trip-chat-app.test.tsx --run` | 通过，3 个测试通过。 |
| `bun run test --run` | 通过，7 个测试文件、21 个测试通过。 |
| `bun run build` | 通过，Next.js 生产构建和 TypeScript 检查通过。 |

## 相关讨论

- 用户补充要求“历史放在左侧”，因此最终没有采用顶部横向历史条。
- 选择在 `TripChatApp` 管理 session 列表和快照恢复，`ChatPanel` 继续专注聊天消息、输入和生成控制，避免把 API 数据流塞进展示组件。
