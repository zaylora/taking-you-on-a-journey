# SSE 错误回显到聊天框

## 任务目标

解决后端 SSE 已推送 `error` 事件时，前端只弹出 toast、没有把「生成失败，请重试」回显到聊天消息区域的问题。

## 改动文件

- `frontend/src/composables/useSSE.ts`
- `frontend/tests/sse.test.ts`

## 改动详情

- 在 `useSSE` 的 `error` 事件分支中读取错误文案，并写入一条 `assistant` 消息。
- 复用现有 `Message.kind = 'error'` 和 `MessageList.vue` 的错误气泡样式。
- 保留原来的 `ElMessage.error(...)` toast 提醒。
- 新增 Bun 测试，覆盖 `session -> error` SSE 流进入 `useSSE.send()` 后，消息列表应包含用户消息和 assistant 错误消息。

## 测试结果

- `cd frontend && bun test ./tests/sse.test.ts`：2 pass。
- `cd frontend && bun run build`：通过。构建输出包含现有 Rolldown 依赖注释警告和动态导入提示，退出码为 0。

## 相关讨论

- 根因是前端已有错误消息类型和错误气泡样式，但 `useSSE.ts` 的 `error` 分支只调用 toast，没有把错误写入 Pinia conversation。
