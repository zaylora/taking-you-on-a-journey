# 助手消息操作按钮生成后显示

## 任务目标

让助手消息底部的「复制 / 赞 / 踩」三个操作按钮只在当前回复生成结束后显示。生成中的最新助手消息不显示这些按钮，避免用户在内容尚未稳定时操作。

## 改动文件清单

| 文件 | 说明 |
| --- | --- |
| `frontend-next/src/components/chat-panel.tsx` | 为助手消息操作按钮增加生成状态判断，隐藏最新生成中的助手消息操作。 |
| `frontend-next/src/components/chat-panel.test.tsx` | 增加生成中隐藏「复制 / 赞 / 踩」按钮的行为测试。 |
| `docs/README.md` | 增加本次改动记录索引。 |

## 改动详情

- 在 `ChatMessageItem` 中新增 `showActions` 条件。
- 当消息不是用户消息、不是错误消息，且不是「当前仍在生成的最新助手消息」时才渲染 `MessageActions`。
- 保留历史已完成助手消息的操作按钮，避免全局 loading 时影响旧回复操作。

## 测试结果

- RED：新增测试后，`bun run test src/components/chat-panel.test.tsx --run` 失败，确认生成中仍会渲染「复制」按钮。
- GREEN：收紧显示条件后，`bun run test src/components/chat-panel.test.tsx --run` 通过，7 个测试全绿。

## 相关讨论

- 本次按最小改动处理为「只隐藏最新生成中助手消息的操作按钮」。
- 如果后续希望全局生成期间隐藏所有历史助手消息按钮，需要另行调整为全局 loading 规则。
