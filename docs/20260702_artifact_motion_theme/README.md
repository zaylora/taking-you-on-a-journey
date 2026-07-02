# Artifact 动画与主题统一

## 任务目标

为 `frontend-next` 右侧行程 Artifact 工作区加入 `motion` 进退场和布局动画，并修复 Artifact 与聊天区主题色不一致的问题。

## 改动文件清单

| 文件 | 说明 |
| --- | --- |
| `frontend-next/src/components/trip-chat-app.tsx` | 用 `motion/react` 包装聊天区和 Artifact 区，加入布局级展开、滑入和退出动画。 |
| `frontend-next/src/components/trip-chat-app.test.tsx` | 增加 Artifact motion 容器断言，避免退回普通静态容器。 |
| `frontend-next/src/app/layout.tsx` | 将 `dark` 主题提升到文档根节点。 |
| `frontend-next/src/app/layout.test.tsx` | 覆盖根布局应用 dark 主题。 |
| `frontend-next/src/components/chat-panel.tsx` | 移除聊天面板局部 `dark`，改由应用根节点统一提供主题。 |
| `frontend-next/src/components/amap-view.tsx` | 将地图配置提示占位层从硬编码浅色改为主题 token。 |
| `frontend-next/src/components/amap-view.test.tsx` | 覆盖地图占位层使用主题 token。 |

## 改动详情

- `TripChatApp` 使用 `AnimatePresence` 和 `motion.div` 管理右侧 Artifact 的打开、关闭和父布局重排，避免只靠 Tailwind 入场类造成动画割裂。
- Artifact 内容组件仍保持 AI Elements 容器职责，不把动画逻辑塞进 `Artifact` 源组件。
- `dark` 放到 `RootLayout` 的 `<html>` 上，聊天区、右侧 Artifact、shadcn/ui token 和 AI Elements 组件共享同一套主题变量。
- 高德地图未配置 Key 时的占位层改用 `bg-muted`、`text-foreground`、`text-muted-foreground`，避免在暗色界面里出现大面积白底。

## 测试结果

- `bun run test src/app/layout.test.tsx src/components/amap-view.test.tsx`：通过，2 个测试文件、3 个测试。
- `bun run test src/components/trip-chat-app.test.tsx`：通过，1 个测试文件、2 个测试。
- `bun run test`：通过，6 个测试文件、19 个测试。
- `bun run build`：通过，Next.js 生产构建和 TypeScript 检查均完成。
- Playwright 打开 `http://localhost:3000`，确认 `document.documentElement.className` 为 `dark h-full font-sans antialiased`。

## 相关讨论

- 用户指出 Artifact 可以放地图，但动画效果与官网不同；本次选择在业务父布局使用 `motion` 做布局动画，不修改 AI Elements 官方组件源码。
- 用户指出主题色不一致，并指定 `dark` 放在 `frontend-next/src/app/layout.tsx`；本次按该方向把主题提升为应用级设置。
