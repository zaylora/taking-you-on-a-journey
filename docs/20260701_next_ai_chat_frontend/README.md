# Next AI Chat 前端目录

## 任务目标

新增 `frontend-next/`，用最新稳定 Next.js、AI SDK、Tailwind CSS 和 shadcn/ui 风格组件实现一个独立聊天前端，对接现有 FastAPI 后端。布局为左侧聊天框；当后端返回攻略结论和 `day_plans` 时，右侧展开类似 Chatbot Artifact 的行程工作区，承载高德地图和每日路线列表。

## 改动文件清单

| 文件 | 说明 |
| --- | --- |
| `frontend-next/` | 新增 Next.js 16 前端目录。 |
| `frontend-next/src/lib/sse.ts` | 解析现有 FastAPI SSE 帧，并按原 `/api/chat` 请求体对接后端。 |
| `frontend-next/src/lib/trip-state.ts` | 纯 reducer，处理 token、tool、final、error 等事件。 |
| `frontend-next/src/components/trip-chat-app.tsx` | 新前端主容器，管理聊天流和 Artifact 展开状态。 |
| `frontend-next/src/components/chat-panel.tsx` | 左侧聊天消息、工具进度、输入框。 |
| `frontend-next/src/components/trip-artifact.tsx` | 右侧行程工作区，显示预算、天数切换和路线列表。 |
| `frontend-next/src/components/amap-view.tsx` | 高德 JS API 地图组件；未配置 Key 时显示提示。 |
| `frontend-next/src/components/ui/*` | shadcn/ui 风格的 Button、Textarea、Badge。 |
| `docs/superpowers/specs/2026-07-01-next-ai-chat-frontend-design.md` | 设计说明。 |
| `docs/superpowers/plans/2026-07-01-next-ai-chat-frontend.md` | 实施计划。 |

## 改动详情

- 保留后端现有自定义 SSE 协议，不把 FastAPI/LangGraph 流改成 AI SDK 原生 wire protocol。
- 新前端使用 Next.js App Router，`page.tsx` 只挂载客户端入口，浏览器 API 和高德 SDK 均在 `"use client"` 组件中处理。
- 高德 loader 改为 `useEffect` 内动态 import，避免 Next 预渲染阶段访问 `window`。
- 移除 create-next-app 默认的 Google Fonts 远程字体加载，改用系统字体，避免离线或网络波动导致 `next build` 失败。
- 消息结构采用 text/tool parts，兼容 Chatbot 文档的 message-parts 思路，也能直接承接当前后端 `tool_call`、`tool_result`、`token` 事件。
- 右侧 Artifact 在 `final.day_plans` 非空时打开；移动端同一组件以覆盖层呈现，避免桌面/移动重复渲染导致可访问树重复。

## 测试结果

- `cd backend && uv run pytest -q`：152 passed, 4 warnings。
- `cd frontend && bun run build`：通过；Vite/Rolldown 对依赖 pure annotation 有 warning。
- `cd frontend-next && bun run test -- --run`：4 files / 7 tests passed。
- `cd frontend-next && bun run lint`：通过。
- `cd frontend-next && bun run build`：通过。
- Playwright 打开 `http://127.0.0.1:3000/`：页面标题、聊天输入和首屏布局正常，控制台无 warning/error。

## 相关讨论

- 用户确认新目录名为 `frontend-next/`，旧 Vue 前端保留。
- 用户要求使用 worktree，因此本任务在 `E:\github\taking-you-on-a-journey-next-ai-chat-frontend` 的 `feature/next-ai-chat-frontend` 分支中完成。
- 本轮只做前端目录和后端对接，不改后端协议、不做登录/分享/部署链路。
