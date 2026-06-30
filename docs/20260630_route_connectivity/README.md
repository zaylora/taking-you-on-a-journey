# 行程交通连接修复

## 任务目标

修复行程地图与卡片中的两个连接缺口：

- 当天第一个地点与第二个地点之间如果插入了餐饮项，必须显示第一段交通。
- 总览模式下，上一天最后一个地点与下一天第一个地点之间必须有地图路线连接；单日 Tab 仍只显示当天路线。

## 改动文件清单

| 文件 | 说明 |
| --- | --- |
| `backend/app/agent/itinerary/fill.py` | 把停靠点追加逻辑统一为“先补交通、再追加点位”，避免景点到餐厅漏交通，并同步推进时间线。 |
| `backend/tests/agent/test_itinerary_fill.py` | 增加景点 → 餐厅 → 景点的交通与时间线回归测试。 |
| `frontend/src/utils/overviewRoute.ts` | 新增总览路线 leg 纯函数，支持总览跨天连接、单日不跨天。 |
| `frontend/src/utils/dayPlanConnectivity.ts` | 对进入前端的旧 `day_plans` 补齐当天相邻真实停靠点之间缺失的 transport 项。 |
| `frontend/src/utils/routeScheduler.ts` | 新增路线请求串行队列，避免总览绘线和预取同时打爆高德 QPS。 |
| `frontend/src/utils/amapErrors.ts` | 识别高德 `CUQPS_HAS_EXCEEDED_THE_LIMIT` 限流错误。 |
| `frontend/src/components/MapView.vue` | 使用总览路线纯函数；总览传入跨天连接，Day Tab 保持当天范围。 |
| `frontend/src/composables/useAMap.ts` | 总览路线规划改为串行限速；限流时静默降级为直线兜底，避免控制台刷屏。 |
| `frontend/src/stores/trip.ts` | `final` 和历史快照写入时统一规范化交通段，旧会话也能补齐第一段交通。 |
| `frontend/tests/overviewRoute.test.ts` | 增加总览跨天连接与单日隔离测试。 |
| `frontend/tests/dayPlanConnectivity.test.ts` | 覆盖旧数据补齐缺失交通、避免重复交通。 |
| `frontend/tests/routeScheduler.test.ts` | 覆盖路线请求串行与过时代次中止。 |
| `frontend/tests/amapErrors.test.ts` | 覆盖高德 QPS 限流错误识别。 |
| `frontend/tests/sse.test.ts` | 同步当前消息 segments 契约，保持前端测试通过。 |

## 改动详情

后端原逻辑在每个景点之后插入午餐，但只在处理下一个景点前补交通，所以会出现“餐厅 → 第二个景点”有交通，而“第一个景点 → 餐厅”没有交通。现在通过 `_append_with_transport()` 统一追加真实停靠点：只要前面已有停靠点，就先插入一条 transport，再追加当前点位；同时保留原停留时长并顺延开始/结束时间，避免交通段与餐饮/景点时间重叠。

前端原 `buildOverviewLegs` 写在 `MapView.vue` 内部，只按每天独立生成路线段，总览时自然不会连接跨天边界。现在将其提取到 `frontend/src/utils/overviewRoute.ts`，并增加 `connectDays` 参数：总览模式连接上一天尾点到下一天首点，单日模式保持当天内部连接。

第二轮排查发现：后端补丁只影响新生成行程，已有会话的旧 `day_plans` 仍可能缺少第一段交通。因此前端在 `setDayPlans()` 与历史快照 `applySnapshot()` 时调用 `normalizeDayPlanTransports()`，对当天相邻真实停靠点补齐缺失 transport，且不会重复插入已有交通段。

地图后半段缺线与控制台 `CUQPS_HAS_EXCEEDED_THE_LIMIT` 对齐：总览一次性并发规划多段路线，同时 `routeInfo` 预取也在请求高德，导致高德 QPS 限流。现在总览绘线与预取共用 `enqueueRouteTask()` 队列，分段串行并加 250ms 间隔；若仍遇到限流，识别后不再刷 warning，并为该段画一条虚线兜底，保证视觉连接不断。

本次没有引入新依赖。连接规则是对现有 `day_plans` 契约的确定性纯映射，使用标准 TypeScript/Python 纯函数更小、更可测；外部路线/地图库仍由既有高德 JS SDK 负责真实路网绘制。

## 测试结果

- `cd backend && uv run pytest -q`：149 passed, 4 warnings。
- `cd frontend && bun test`：9 passed。
- `cd frontend && bun run build`：成功。构建输出仍有依赖 `@vueuse/core` 的 Rolldown pure annotation 警告，以及既有 `App.vue` 动静态导入提示，不影响退出码。

## 相关讨论

- 后端负责保证当天相邻真实停靠点之间都有交通卡，避免卡片列表缺段。
- 前端负责地图总览的跨天路线连续性；按 Day 查看时不跨天，避免单天视图混入其他天的路线。
- 前端还负责兼容旧会话的已存 `day_plans`，避免用户必须重新生成行程才能看到补齐后的交通卡。
- 高德路线规划是外部限流服务，总览路线必须限速串行；限流时用兜底直线保持可读性。
- 交通卡本身仍使用现有 `mode: "市内交通"` 与前端高德路线规划，未改变后端/前端共享数据结构。
