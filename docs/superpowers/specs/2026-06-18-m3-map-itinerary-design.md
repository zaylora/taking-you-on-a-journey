# M3 设计：地图与行程联动

- 日期：2026-06-18
- 里程碑：M3（地图与行程联动）
- 范围：纯前端联动层，**不改后端**
- 验收标准（策划书第八章）：生成行程后地图自动打点；点击卡片地图高亮

## 决策摘要

| 决策点 | 选择 | 说明 |
|---|---|---|
| 高德 JS API Key | 占位 + 加载守卫 | 读 `VITE_AMAP_JS_KEY`，缺失时地图区显示友好提示，不阻断结构落地 |
| POI 后端代理 `/api/map/*` | 不纳入本轮（留 M5） | `map_proxy.py` 保持空壳；打点只用 `day_plans` 已有坐标，无需实时 POI 搜索 |
| 联动方向 | 双向 | 卡片→地图（平移+高亮+InfoWindow）且 marker→卡片（高亮+滚动） |
| 右侧布局 | 地图铺满 + 右侧竖向悬浮行程面板（可收起） | 移除原上下分栏，地图视野最大化 |

## 1. 架构与数据流

M3 不改后端：`day_plans` 契约已由 `itinerary.py` 产出，`map_proxy.py` 按严格验收版保持空壳。

```
后端 final 事件
   └─ day_plans  ──setDayPlans──▶  tripStore.dayPlans (DayPlan[])
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              ▼                         ▼                          ▼
        MapView.vue               ResultPanel.vue            tripStore
       (useAMap 渲染)            (逐日卡片列表)          activeDay/activePoiId
              │                         │                          ▲
              │  watch(activePoiId) ───┼── 卡片 click ────────────┘
              │  → 平移+高亮+InfoWindow │
              └── marker click ─────────┴──────────────────────────┘
                  → 反向设 activePoiId（卡片高亮+滚动到视图）
```

- 单一数据源：`tripStore`。联动状态 `activeDay`、`activePoiId` 由 store 持有；MapView 与 ResultPanel 都只读+写它，互不直接引用。
- 双向联动不产生循环：写入与当前相同的值不重复触发响应；marker 点击与卡片点击最终都收敛到同一个 `activePoiId`。

## 2. 类型契约（`frontend/src/types/index.ts` 新增）

与后端 `backend/app/graph/nodes/itinerary.py` 产出对齐，把 `dayPlans: any[]` 收紧为强类型。

```ts
export interface LngLat { lng: number; lat: number }
export interface DayWeather { text: string; temp: string; is_rainy: boolean; source: string }
export interface TripItem {
  type: 'attraction' | 'meal'
  name: string
  poi_id: string
  location: LngLat
  indoor?: boolean        // 仅 attraction 有
}
export interface DayPlan {
  day: number
  items: TripItem[]
  center: LngLat
  weather: DayWeather
}
```

- `FinalPayload.day_plans` 与 store 的 `dayPlans` 都换成 `DayPlan[]`。
- `poi_id` 作为联动主键（唯一标识一个 item）。

## 3. store 扩展（`frontend/src/stores/trip.ts`）

新增联动状态与 action，其余不动。

```ts
const activeDay   = ref<number | null>(null)   // 当前聚焦的天，切天换 marker 配色焦点
const activePoiId = ref<string | null>(null)   // 当前高亮的 item（联动主键）

const setActiveDay = (d: number | null) => { activeDay.value = d }
const setActivePoi = (id: string | null) => { activePoiId.value = id }
// setDayPlans 末尾：非空则默认 activeDay=1；清空则重置两个 active
```

`setDayPlans` 收到非空数据时自动 `activeDay=1`，让地图首屏就有焦点。

## 4. useAMap 封装（`frontend/src/composables/useAMap.ts`）

把高德 SDK 细节关进一个 composable，MapView 只调它的方法，便于独立理解与替换。

```ts
useAMap(containerRef): {
  ready: Ref<boolean>           // SDK + 地图实例就绪
  error: Ref<string | null>     // key 缺失/加载失败的友好文案
  renderDayPlans(plans, activeDay): void   // 清旧 marker、按天配色重绘、自适应视野 setFitView
  focusPoi(poiId): void         // 平移 setCenter + 放大该 marker + 打开 InfoWindow
  onMarkerClick(cb): void       // 注册 marker 点击回调（回写 activePoiId 用）
}
```

要点：

- Key 读 `import.meta.env.VITE_AMAP_JS_KEY`；缺失时 `error` 置文案、不调 `AMapLoader.load`（加载守卫）。
- `AMapLoader.load({ key, version: '2.0', plugins: ['AMap.InfoWindow'] })`；地图实例与 marker 存在闭包里，组件卸载时 `map.destroy()`。
- 按天配色：marker 颜色由 `day` 决定（一组预设色循环）；`activeDay` 那天的 marker 高亮，其余淡化。
- `renderDayPlans` 渲染后用 `setFitView` 自适应视野；切天调用 `setActiveDay` → MapView watch 触发重绘焦点。

## 5. MapView 与 ResultPanel + 布局

**MapView.vue**

- 容器 `ref` + `useAMap`。
- `watch(dayPlans)` → `renderDayPlans`；`watch(activePoiId)` → `focusPoi`；`onMarkerClick` → `setActivePoi`。
- `error` 非空时盖一层"请在 .env 配置 VITE_AMAP_JS_KEY"提示（替代当前占位）。
- 无 day_plans 时显示空态。

**ResultPanel.vue（右侧竖向悬浮面板，可收起）**

- 绝对定位贴右缘，浮在地图上；顶部 Day Tab（`Day1 / Day2…`，点击 `setActiveDay` + 重绘焦点）。
- 当天 `items` 竖向时间线卡片：图标（景点/餐厅）、名称、`indoor` 标记、天气。
- 卡片 `click → setActivePoi(poi_id)`；`activePoiId` 命中则高亮 + `scrollIntoView`。
- 右上"» 收起"按钮：收起后只留右缘窄把手，地图视野最大化。

**App.vue**

- 右侧容器改为相对定位，内放 `<MapView/>`（铺满）+ `<ResultPanel/>`（绝对悬浮）。
- 移除上下分栏。

## 错误处理

- Key 缺失 / SDK 加载失败：`useAMap.error` 置文案，MapView 显示提示层，不崩溃；行程面板仍可正常显示卡片。
- `day_plans` 为空或 item 无合法 `location`：MapView 空态；ResultPanel 不渲染卡片。
- 双向联动：写入相同值不重复触发，避免 watch 循环。

## 测试与验证

- 前端构建：`bun run build`（tsc + vite）须通过，强类型 `DayPlan` 不报错。
- 手动验收路径：发起一次完整规划 → 收到 final → 地图自动打点并 `setFitView` → 点击某张卡片 → 地图平移+高亮+InfoWindow → 点击某 marker → 对应卡片高亮并滚动可见 → 切 Day Tab → marker 焦点切换 → 收起面板 → 地图视野最大化。
- Key 缺失场景：清空 `VITE_AMAP_JS_KEY` → 地图区显示配置提示，应用其余功能不受影响。

## 不在本轮范围（YAGNI）

- POI 实时搜索 / 后端 `/api/map/*` 代理（留 M5）。
- 点选新增景点、行程拖拽重排（留 M5）。
- 路线规划连线（仅打点，不连线）。
