# 行程交通连接修复

## 任务目标

修复两类路线断点：

- 当天第一个真实地点与餐饮项之间缺少交通卡。
- 总览地图没有连接上一天最后一个地点与下一天第一个地点。

## 改动文件清单

| 文件 | 说明 |
| --- | --- |
| `backend/app/agent/itinerary/fill.py` | 统一真实停靠点追加逻辑，补齐任意相邻点之间的 transport 项并顺延时间。 |
| `backend/tests/agent/test_itinerary_fill.py` | 增加景点、餐饮、景点之间交通完整性的回归测试。 |
| `frontend/src/utils/overviewRoute.ts` | 新增路线 leg 构造纯函数，支持跨天连接开关。 |
| `frontend/src/utils/dayPlanConnectivity.ts` | 规范化旧行程数据，补齐当天缺失的相邻交通段。 |
| `frontend/src/utils/routeScheduler.ts` | 串行化路线请求，降低高德 QPS 压力。 |
| `frontend/src/utils/amapErrors.ts` | 识别高德 QPS 限流错误。 |
| `frontend/src/components/MapView.vue` | 总览模式启用跨天连接，Day Tab 保持当天路线。 |
| `frontend/src/composables/useAMap.ts` | 总览路线按队列串行绘制，限流时画虚线兜底。 |
| `frontend/src/stores/trip.ts` | 写入 final 与历史快照时统一补齐旧数据缺失交通。 |
| `frontend/tests/overviewRoute.test.ts` | 覆盖总览跨天连接和单日不跨天。 |
| `frontend/tests/dayPlanConnectivity.test.ts` | 覆盖旧数据交通补齐和去重。 |
| `frontend/tests/routeScheduler.test.ts` | 覆盖路线请求串行和过期绘制中止。 |
| `frontend/tests/amapErrors.test.ts` | 覆盖限流错误识别。 |
| `frontend/tests/sse.test.ts` | 更新测试期望以匹配当前 segments 文本消息契约。 |

## 改动详情

后端原本只在处理下一个景点前补交通。若第一个景点后插入午餐，第一段“景点 → 餐厅”会被漏掉。新 helper `_append_with_transport()` 将“补交通 + 追加点位 + 推进时间”集中处理，因此餐饮与景点都走同一套相邻连接逻辑。

前端将 `MapView.vue` 中的路线拆段逻辑提取为 `buildOverviewLegs()`。总览调用时传 `connectDays=true`，会把前一天尾点连接到下一天首点；按天查看仍传单日计划，不跨天。

继续排查后确认两个追加根因：

- 已有会话里的旧 `day_plans` 不会因为后端补丁自动重算，所以前端写入/加载时需要补齐缺失的当天相邻交通段。
- 总览和预取同时向高德发多段路线请求，会触发 `CUQPS_HAS_EXCEEDED_THE_LIMIT`，导致后续路线段失败。现在路线请求统一进入队列串行执行；总览规划仍失败时使用虚线直连兜底。

未引入新依赖。原因：这次是现有结构化数据到地图路线段的纯转换，成熟第三方库无法替代项目内的业务契约判断；手写纯函数更轻、更容易单测。

## 测试结果

- `cd backend && uv run pytest -q`：149 passed, 4 warnings。
- `cd frontend && bun test`：9 passed。
- `cd frontend && bun run build`：成功，有既有构建警告但退出码为 0。

## 相关讨论

- 后端解决卡片列表中交通项缺失。
- 前端解决旧会话卡片交通缺失、总览地图跨天路线断开，以及高德 QPS 限流导致的后半段缺线。
- 单日视图仍保持当天隔离，避免 Day 1 面板画到 Day 2。
