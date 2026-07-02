# 修复空 POI ID 导致的路线项 key 冲突

## 任务目标

修复 `frontend-next` 行程 Artifact 中路线项渲染时报出的 React duplicate key 警告。问题场景是多个行程项的 `poi_id` 都为空字符串时，React 收到重复的空 key。

## 改动文件清单

| 文件 | 说明 |
| --- | --- |
| `frontend-next/src/components/trip-artifact.tsx` | 将路线项 key 的兜底逻辑从只处理 `null/undefined` 改为同时处理空字符串。 |
| `frontend-next/src/components/trip-artifact.test.tsx` | 新增回归测试，覆盖两个空 `poi_id` 行程项不会触发 duplicate key 警告。 |
| `docs/20260702_trip_artifact_empty_poi_key/README.md` | 本次改动记录。 |
| `docs/README.md` | 增加本次改动索引。 |

## 改动详情

- 根因：原代码使用 `item.poi_id ?? fallback` 作为 React key，空字符串不会触发 `??` 兜底，因此多个 `poi_id: ""` 会得到相同的空字符串 key。
- 修复：改为 `item.poi_id || fallback`，让空字符串也使用 `${item.type}-${index}` 作为兜底 key。
- 取舍：只修复当前报错路径，不额外改动点击选中、地图联动或后端数据结构。

## 测试结果

- `bunx vitest run src/components/trip-artifact.test.tsx`：通过，1 个测试。
- `bunx vitest run`：通过，7 个测试文件、20 个测试。
- `bun run build`：通过。

## 相关讨论

- 该问题来自前端渲染层对空字符串 ID 的处理，不需要修改 SSE 数据契约。
