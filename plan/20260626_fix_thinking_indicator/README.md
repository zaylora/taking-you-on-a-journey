# 修复"正在思考"提示在工具收尾后消失

## 任务目标

截图反馈：工具调用链上的 pill 已全部打勾（✓ done），但界面没有任何"正在思考"提示，看起来像卡住了。实际上此时 Agent 仍在思考下一步 / 生成最终答案。

## 根因

`MessageList.vue` 原 `showThinking` 判断条件为：

```
loading 且 最后一条 assistant 消息 既无 toolSteps 也无 content
```

但在 ReAct 串行循环里存在一个窗口：
1. `endToolCall` 把当前工具 pill 标成 ✓(done)
2. Agent 思考下一步 / 等待正文 token（`content` 仍为空，也没有正在 running 的工具）
3. 下一个工具开始 或 正文 token 流入

在第 2 步，`toolSteps?.length` 为真 → `showThinking=false`，于是只剩一排打勾的工具，没有任何加载提示。

## 改动文件

- `frontend/src/components/MessageList.vue`

## 改动详情

将"是否还在思考"的判断从「有没有工具链」改为「有没有正文 + 有没有正在转的工具」，并拆成两种展示：

- `showStandaloneThinking`：尚无 assistant 占位消息（最后一条仍是用户/澄清）时，用独立带头像的气泡。
- `inlineThinking(msg, index)`：对最后一条 assistant 消息，当 `loading` 且 `content` 为空且没有 `status==='running'` 的工具时，在同一气泡内联展示加载提示。覆盖「工具收尾后」与「工具间」的思考窗口，避免再起一个独立 AI 气泡造成双块。

样式新增 `.content > .thinking-bubble:not(:first-child)` 上间距，使内联提示与工具链/正文分隔。

## 测试结果

- `npx vue-tsc --noEmit` 通过（EXIT 0）。

## 相关讨论

- 内联而非独立气泡：工具链 pill 与思考提示属于同一轮 assistant 回合，挂在同一条消息上与历史快照「单条消息内聚合」形态一致。
- 当某个工具正在 `running` 时不显示内联提示，因为此时 pill 自带转圈 loading，避免重复 spinner。
