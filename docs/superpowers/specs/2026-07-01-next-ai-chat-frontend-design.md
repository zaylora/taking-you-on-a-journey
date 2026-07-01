# Next AI Chat Frontend 设计

## 目标

新增 `frontend-next/`，用 Next.js 16、AI SDK 7、Tailwind CSS 和 shadcn/ui 做一个独立前端目录，对接现有 FastAPI 后端。旧 `frontend/` 和后端协议不在本任务中重写。

## 假设

- 后端继续提供 `POST /api/chat` 的自定义 SSE 流，事件名沿用 `session`、`token`、`tool_call`、`tool_result`、`clarify`、`final`、`error`。
- 会话接口继续使用 `GET/POST/DELETE /api/sessions`。
- 新前端用 `NEXT_PUBLIC_API_BASE` 指向 FastAPI，默认 `http://localhost:8000`。
- 高德 JS API Key 使用 `NEXT_PUBLIC_AMAP_JS_KEY`，安全密钥使用 `NEXT_PUBLIC_AMAP_SECURITY_CODE`。这两个本来就是浏览器侧 Key，不复用后端 Web 服务 Key。

## 方案

`frontend-next/src/app/page.tsx` 保持 Server Component，只渲染客户端入口 `TripChatApp`。所有聊天状态、SSE 读取、地图加载和用户交互都放在 `"use client"` 模块里，避免服务端渲染访问 `window` 或高德 SDK。

聊天区使用 AI SDK 兼容的数据形态，但不强行把后端改成 AI SDK wire protocol。客户端保留一层 `fetchTripChatStream`，负责解析现有 SSE 事件并更新消息 parts。这样能使用 Next 和 AI SDK 生态，同时不破坏后端 LangGraph/FastAPI 当前契约。

右侧结果区实现为 Chatbot 文档中 Artifact/Canvas 类似的展开体验：默认聊天占满主屏；当收到 `final.day_plans` 后，右侧滑出一个行程 Artifact，包含高德地图、预算条、天数切换、路线/点位列表。移动端改为底部/全屏抽屉式布局。

新前端使用 bun 管理依赖和运行脚本。字体使用系统字体，不依赖构建期访问 Google Fonts。

## 文件边界

- `frontend-next/src/lib/types.ts`：后端事件和行程数据类型。
- `frontend-next/src/lib/sse.ts`：SSE 文本解析和 fetch 适配。
- `frontend-next/src/lib/trip-state.ts`：纯 reducer，接收事件生成 UI 状态。
- `frontend-next/src/components/trip-chat-app.tsx`：客户端应用容器。
- `frontend-next/src/components/chat-panel.tsx`：聊天消息、工具步骤、输入框。
- `frontend-next/src/components/trip-artifact.tsx`：右侧展开面板。
- `frontend-next/src/components/amap-view.tsx`：高德地图加载、打点、路线。
- `frontend-next/src/components/ui/*`：shadcn/ui 风格基础组件。

## 不做

- 不改后端 SSE 协议。
- 不迁移旧 Vue 前端。
- 不做登录、分享、数据库或 Vercel 部署链路。
- 不实现真实预订、支付或写入长期记忆。

## 验证

- `cd backend && uv run pytest -q`
- `cd frontend && bun run build`
- `cd frontend-next && bun run test -- --run`
- `cd frontend-next && bun run lint`
- `cd frontend-next && bun run build`
