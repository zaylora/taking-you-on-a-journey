# AI Elements 运行态组件迁移

## 任务目标

将 `frontend-next` 聊天消息中的运行状态统一改为 AI Elements 组件：加载和工具运行态使用 `Shimmer`，推理过程使用 `Reasoning`，工具调用使用 `Tool`。用户更正后，历史消息继续展示，不做隐藏。

## 改动文件清单

| 文件 | 说明 |
| --- | --- |
| `frontend-next/src/components/chat-panel.tsx` | 接入 `Shimmer`、`Reasoning`、`Tool`，保留历史消息渲染。 |
| `frontend-next/src/components/chat-panel.test.tsx` | 增加运行态组件断言，并恢复历史消息展示测试。 |
| `frontend-next/src/lib/types.ts` | 为 Next 版 UI 状态补充 node 进度和当前思考 label 字段。 |
| `frontend-next/src/lib/trip-state.ts` | 处理 `node_start` / `node_end`，并按工具 label 精确完成工具调用。 |
| `frontend-next/src/lib/trip-state.test.ts` | 覆盖思考阶段 label、重复工具调用开始/停止标记。 |
| `frontend-next/src/components/trip-chat-app.tsx` | 将当前 node label 传入聊天面板，并在提交/停止时清理运行态。 |
| `frontend-next/src/components/ai-elements/reasoning.tsx` | AI Elements 生成的推理折叠组件。 |
| `frontend-next/src/components/ai-elements/tool.tsx` | AI Elements 生成的工具调用组件。 |
| `frontend-next/src/components/ai-elements/shimmer.tsx` | AI Elements 生成的文字 shimmer 组件。 |
| `frontend-next/src/components/ai-elements/code-block.tsx` | `Tool` 输出展示依赖的代码块组件。 |
| `frontend-next/src/components/ui/collapsible.tsx` | `Reasoning` 和 `Tool` 依赖的折叠基础组件。 |
| `frontend-next/src/components/ui/badge.tsx` | 增加 `variant="secondary"` 兼容，满足 `Tool` 组件类型要求。 |
| `frontend-next/src/app/layout.tsx` | 移除 Google Fonts 构建时请求，避免生产构建依赖外网字体。 |
| `frontend-next/src/app/globals.css` | 为 `--font-sans` 指定本地系统字体栈。 |
| `frontend-next/package.json` / `frontend-next/bun.lock` | 增加 AI Elements 组件所需依赖。 |

## 改动详情

- 加载中的全局生成提示改为 `Shimmer`，工具运行中的状态文案也改为 shimmer 效果。
- 助手消息中，位于工具调用之前的文本片段渲染为 `Reasoning`，最后一段文本仍作为正式 Markdown 回复显示。
- 工具调用不展示后端原始入参和结果，只用已有脱敏后的 `tool`、`label`、`status` 渲染 `ToolHeader` 和运行/完成状态，符合现有安全约定。
- 对齐 Vue 版 SSE 逻辑，Next 版现在会消费 `node_start` / `node_end` 的 label，在尚未输出正文且没有工具运行时展示后端阶段提示，例如“正在思考...”。
- 工具的开始/停止标记改为由 `tool_call` / `tool_result` 控制；重复同类工具会优先用 `label` 精确匹配，避免并发搜索时提前把未完成工具标成完成。
- 历史消息继续通过 `messages.map(...)` 全量渲染，撤销“只显示最新一轮”的误解。
- `next/font/google` 会在生产构建时请求 Google Fonts。本项目构建环境中该请求失败，因此改成本地系统字体栈，保证 `bun run build` 可离线完成。

## 测试结果

- `cd frontend-next && bun run test src/lib/trip-state.test.ts src/components/chat-panel.test.tsx`：10 个测试通过。
- `cd frontend-next && bun run build`：构建通过。
- `cd frontend-next && bun run test`：全量结果见最终回复。

## 相关讨论

- 用户明确要求前端 UI 库以 `elements.ai-sdk` 为准，并进一步指定加载/运行态、推理过程、工具调用分别使用 `shimmer`、`reasoning`、`/components/tool`。
- 用户更正第一点为“去掉，需要历史”，因此聊天历史必须保留展示。
