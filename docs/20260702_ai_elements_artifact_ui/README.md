# AI Elements Artifact UI

## 任务目标

将 `frontend-next` 聊天页 UI 基准切换为 AI Elements：消息、Markdown 响应、输入区和右侧行程 Artifact 工作区都改为组合 AI Elements 组件；右侧内容仍保留地图和行程卡片。

## 改动文件清单

| 文件 | 说明 |
| --- | --- |
| `frontend-next/components.json` | 新增 AI Elements/shadcn 组件配置。 |
| `frontend-next/package.json`、`frontend-next/bun.lock` | 新增 AI Elements 生成组件所需依赖，如 `streamdown`、`use-stick-to-bottom`、`radix-ui` 等。 |
| `frontend-next/src/components/ai-elements/*` | 通过 AI Elements CLI 生成 `artifact`、`conversation`、`message`、`prompt-input`。 |
| `frontend-next/src/components/ui/*` | 通过 CLI 生成或更新 AI Elements 依赖的基础 UI 组件。 |
| `frontend-next/src/components/chat-panel.tsx` | 用 AI Elements Conversation/Message/PromptInput 重写聊天面板。 |
| `frontend-next/src/components/trip-artifact.tsx` | 用 AI Elements Artifact 重写右侧工作区外壳，保留地图和行程卡片。 |
| `frontend-next/src/components/chat-panel.test.tsx`、`trip-chat-app.test.tsx` | 增加 AI Elements 结构和既有行为断言。 |
| `frontend-next/src/app/layout.tsx` | 增加 `TooltipProvider`。 |
| `frontend-next/src/test/setup.ts` | 为 jsdom 增加 `ResizeObserver` polyfill。 |
| `docs/superpowers/specs/2026-07-02-ai-elements-artifact-ui-design.md` | 设计说明。 |
| `docs/superpowers/plans/2026-07-02-ai-elements-artifact-ui.md` | 实施计划。 |

## 改动详情

- 按官方方式运行 AI Elements CLI，组件源码落到 `src/components/ai-elements/`，后续 React 前端 UI 以该目录组件为准。
- `ChatPanel` 不再手写 `ReactMarkdown` 和自定义表单，改用 `Conversation`、`MessageResponse`、`PromptInput` 等组件。
- `TripArtifact` 改用 `Artifact` 组件体系承载地图、预算摘要、Day tab 和路线卡片，形成右侧 workspace 观感。
- 保留现有 SSE 数据流、reducer state、地图组件和 POI/Day 联动逻辑。

## 测试结果

```bash
cd frontend-next && bun run test
# 5 passed, 11 passed

cd frontend-next && bun run build
# Next.js production build and TypeScript passed
```

## 相关讨论

- 用户明确要求 `frontend-next` UI 库以 `https://elements.ai-sdk.dev/` 为准，因此选择官方 CLI 生成源码组件，而不是继续手写同名外壳。
- AI Elements 的 `MessageResponse` 使用 Streamdown，链接在测试环境中呈现为可点击 button；测试按用户可见行为断言，不绑定旧 DOM 标签。
- 本次迁移限定在聊天页核心链路，不改后端协议和地图能力，避免扩大风险。
