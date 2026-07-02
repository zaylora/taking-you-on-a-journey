# AI Elements Artifact UI Design

## Task Goal

将 `frontend-next` 的聊天页 UI 基准切换为 AI Elements，并替换聊天页所有可直接由 AI Elements 承载的 UI：消息列表、Markdown 响应、输入区、右侧 Artifact 工作区。右侧工作区保留现有地图和行程卡片业务内容，但使用 AI Elements 的 Artifact 组件作为外壳，替代旧的自写右侧弹出面板观感。

## Scope

- 当前任务覆盖 `frontend-next` 聊天页的核心交互链路：`Conversation`、`Message`、`PromptInput`、`Artifact`。
- AI Elements 组件通过官方 CLI 安装到 `frontend-next/src/components/ai-elements/`，作为后续 React 前端 UI 的默认基准；聊天页内凡是已有 AI Elements 对应组件的部分，都优先用 AI Elements 组合。
- 右侧 Artifact 内容仍为地图和行程卡片，不改为纯 Markdown 文档。
- 不一次性迁移所有基础 UI、路由、地图封装或后端 SSE 协议。

## Architecture

`TripChatApp` 继续持有现有 reducer state 和 SSE 数据流；`ChatPanel` 和 `TripArtifact` 负责把 state 映射到 AI Elements 组件。`ChatPanel` 使用 `Conversation`、`ConversationContent`、`ConversationScrollButton`、`Message`、`MessageContent`、`MessageResponse`、`MessageActions`、`MessageAction`、`PromptInput`、`PromptInputTextarea`、`PromptInputSubmit`。`TripArtifact` 使用 `Artifact`、`ArtifactHeader`、`ArtifactTitle`、`ArtifactDescription`、`ArtifactActions`、`ArtifactAction`、`ArtifactClose`、`ArtifactContent` 构成右侧 workspace shell，内部仍组合 `AmapView` 与行程文档式卡片。

AI Elements 是源码型 UI 组件：安装后代码进入项目内，不从运行时包导入。项目可在业务组件里通过 `className` 做少量产品化样式，但新增聊天/Artifact UI 优先组合 AI Elements，而不是继续扩展自写壳。

## Components

- `src/components/ai-elements/artifact.tsx`: 官方 Artifact 组件，作为右侧工作区外壳。
- `src/components/ai-elements/conversation.tsx`: 官方 Conversation 组件，承载消息滚动容器和回到底部按钮。
- `src/components/ai-elements/message.tsx`: 官方 Message 组件，承载用户/助手消息、Markdown 响应和消息操作。
- `src/components/ai-elements/prompt-input.tsx`: 官方 Prompt Input 组件，承载输入框、工具区和提交/停止按钮。
- `src/components/trip-artifact.tsx`: 业务 Artifact，把行程地图、预算、Day tab、路线卡片放进 AI Elements Artifact。
- `src/components/chat-panel.tsx`: 用 AI Elements 的 conversation/message/prompt-input 替换当前自写消息/输入结构，保持既有发送与停止回调。
- `src/components/trip-chat-app.tsx`: 继续控制打开/关闭右侧 Artifact；调整容器动画和宽度，形成和参考站一致的并排 workspace。

## UI Behavior

- 当 `artifactOpen` 为 true 时，右侧工作区从右侧丝滑滑入，左侧聊天区域保持可用。
- Artifact 顶部展示关闭按钮、标题“行程地图”、描述“X 天路线 / 等待生成结果”，并提供刷新、复制、下载等图标按钮占位；没有真实业务能力的按钮只保留可访问标签，不触发副作用。
- Artifact 内容上半部为地图，下半部为文档式行程内容：预算摘要、Day 分段、POI/餐饮/交通/酒店条目。
- 选中 Day 或 POI 时沿用现有 `activeDay`、`activePoiId` 联动。
- 聊天消息由 AI Elements `Message` 呈现，助手 Markdown 由 `MessageResponse` 呈现；不再在聊天页手写 `ReactMarkdown` 渲染层。
- 输入区由 AI Elements `PromptInput` 呈现，保持“发送消息”可访问标签、Enter 提交、加载中停止生成。

## Testing

- 更新 `trip-chat-app.test.tsx`，断言右侧以 AI Elements Artifact 结构渲染，地图和行程卡片仍可见。
- 更新 `chat-panel.test.tsx`，断言 Markdown 消息、发送、停止生成仍符合既有行为，并能通过 AI Elements 的 message / prompt input 结构查询到核心 UI。
- 运行 `bun run test` 和 `bun run build`，确保 React/Next 类型检查和测试通过。

## Decisions

- 选择 AI Elements 官方 CLI 而不是手写同名组件，原因是用户明确要求 UI 库以 `https://elements.ai-sdk.dev/` 为准。
- 选择迁移聊天页所有已有 AI Elements 对应组件的 UI，原因是用户明确要求“包括消息之类的也都替换掉”。
- 选择保留业务数据流和地图组件，原因是本次目标是视觉与交互外壳迁移，不改变后端协议和地图能力。
