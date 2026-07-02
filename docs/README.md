# 改动记录索引

| 日期 | 目录 | 概述 |
| --- | --- | --- |
| 2026-07-02 | `docs/20260702_message_actions_after_generation/` | 让 `frontend-next` 助手消息底部的「复制 / 赞 / 踩」按钮只在当前回复生成结束后显示，并补充生成中隐藏按钮的行为测试。 |
| 2026-07-02 | `docs/20260702_remove_generating_double_scrollbar/` | 去掉 `frontend-next` 聊天区的「正在生成」通用 loading 文案；确认 `use-stick-to-bottom` 内部已创建实际滚动层，将 `Conversation` 外层改为 `overflow-y-hidden`，避免出现双滚动条。 |
| 2026-07-02 | `docs/20260702_chat_scrollbar_layout/` | 确认 `Reasoning` 已接入；将聊天区滚动条与输入框布局对齐官网 ChatGPT 示例：由悬浮 hack 改为 flex 两段式，修复滚动条贯穿窗口底部与遮挡输入框，并为 `.dark` 补 `color-scheme: dark` 使原生滚动条变深色。 |
| 2026-07-02 | `docs/20260702_ai_elements_runtime_states/` | 将 `frontend-next` 加载/运行、推理过程和工具调用迁移到 AI Elements 的 `Shimmer`、`Reasoning`、`Tool`，并保留历史消息展示。 |
| 2026-07-02 | `docs/20260702_ai_elements_artifact_ui/` | 将 `frontend-next` 聊天页可用 UI 迁移到 AI Elements：消息、输入区和右侧行程 Artifact 工作区都改为组合 AI Elements 组件。 |
| 2026-07-02 | `docs/20260702_next_chatbox_ui_markdown/` | 将 `frontend-next` 聊天框改为 Vercel AI Chatbot 风格暗色 UI，新增多消息会话请求历史和 Markdown 渲染。 |
| 2026-07-01 | `docs/20260701_next_ai_chat_frontend/` | 新增 `frontend-next/`：Next.js 16 + AI SDK + Tailwind + shadcn/ui 风格聊天前端，对接现有 FastAPI SSE，并在生成行程后展开高德地图 Artifact 工作区。 |
| 2026-06-30 | `docs/20260630_route_connectivity/` | 修复当天景点到餐饮缺交通、旧会话交通缺段、总览地图跨天不连线和高德 QPS 限流导致后半段缺线的问题。 |
