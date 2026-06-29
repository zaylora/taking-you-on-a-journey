# Task 7: MessageList 顺序渲染 segments，reasoning 写完折叠

## 任务目标

重写 `MessageList.vue` 按 segments 顺序渲染：工具 pill + 淡色可折叠的中间推理 + 黑色常展开的最终回复。删除不再被引用的 `AgentProgress.vue`。让 `bun run build` 从红转绿。

## 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `frontend/src/components/MessageList.vue` | 修改 | 重写模板/脚本，移除 AgentProgress import 与 clarify-answer emit |
| `frontend/src/components/AgentProgress.vue` | 删除 | 已无引用，用 git rm 删除 |

## 改动详情

### MessageList.vue

**模板变更：**
- 移除 `<AgentProgress>` 组件引用
- 移除 `msg.content` 的直接渲染块
- 移除 `clarify-options` 整块（澄清选项移至 Task 8 的 ClarifyPanel）
- 新增 `<template v-for="(seg, sIdx) in displaySegments(msg)">` 遍历 segments
  - `kind === 'tool'`：渲染 node-pill（运行中显示 loading spinner，完成显示 ✓）
  - `seg.role === 'answer'`：最后一个 text 段，黑色 markdown-body 常展开
  - 其余 text 段（reasoning）：淡色，写完折叠为「已思考」，可点击展开

**脚本变更：**
- 移除 `import AgentProgress from './AgentProgress.vue'`
- 移除 `emit` 定义（clarify-answer 移至 ClarifyPanel）
- 新增 `DisplaySegment` 类型（渲染期动态标 role）
- 新增 `displaySegments()` 函数：最后一个 text 段标为 answer，其余标为 reasoning
- 新增 `manuallyOpen` ref + `toggleReasoning` + `isReasoningOpen`（折叠状态管理）
- 重写 `inlineThinking()`：从 `msg.content` 改为检查 `msg.segments`

**样式变更：**
- 移除 `.clarify-options`
- 从 AgentProgress 迁移 pill 样式（`.node-pill`、`.loading-icon`、`.done-icon`）
- 新增 reasoning 折叠块样式（`.reasoning-block`、`.reasoning-head`、`.reasoning-body`）

### AgentProgress.vue

已无任何组件引用（grep 确认），用 `git rm` 删除。

## 是否连带修改 ChatPanel.vue

**未修改**。ChatPanel 中 `@clarify-answer="send"` 在 Vue 3 中对不存在的 emit 监听会被忽略，vue-tsc 不报错，build 全绿。待 Task 8 时正式清理。

## 测试结果

```
$ cd frontend && bun run build
vue-tsc -b  →  无类型错误
vite build  →  ✓ built in 15.93s
```

## 相关讨论

- `reasoning` 折叠逻辑：流式写入中（loading=true 且是最后消息的最后段）自动展开，写完（后面来了新段或 loading 结束）自动折叠。用户可手动点击覆盖。
- `displaySegments` 是纯渲染期函数，不修改 store 数据，与历史快照结构兼容。
