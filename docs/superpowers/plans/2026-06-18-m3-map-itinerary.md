# M3 地图与行程联动 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 前端消费后端 `day_plans`，在高德地图上自动打点，并实现行程卡片 ↔ 地图 marker 的双向联动。

**Architecture:** 纯前端联动层，不改后端。单一数据源 `tripStore` 持有 `dayPlans` 与联动状态（`activeDay`/`activePoiId`）；`MapView`（经 `useAMap` 封装高德 SDK）与 `ResultPanel`（右侧竖向悬浮可收起面板）都只读+写 store，互不直接引用，通过 `watch` 收敛实现双向联动且不产生循环。

**Tech Stack:** Vue 3.5（`<script setup>` + composition）、Pinia 3、TypeScript、Element Plus 2.14、`@amap/amap-jsapi-loader`（高德 JS API 2.0）、Vite 8、bun。

## Global Constraints

- 全程界面文案与注释用简体中文，永不使用日语。
- 不改后端；`backend/app/api/map_proxy.py` 保持空壳（POI 代理留 M5）。
- 高德 JS API Key 读 `import.meta.env.VITE_AMAP_JS_KEY`；缺失时地图区显示友好提示，不崩溃、不阻断行程面板（加载守卫）。Key 仅前端 JS Key，绝不复用后端 Web 服务 Key。
- 打点只用 `day_plans` 已有坐标，不做实时 POI 搜索、不连线、不拖拽重排（YAGNI，留 M5）。
- 前端无单测框架（无 vitest，且地图 SDK 需真实浏览器）。每个任务的验证 = `bun run build` 类型检查通过（类型即契约）+ 指定的手动验收。所有命令在 `frontend/` 目录下执行。
- `poi_id` 为联动主键，唯一标识一个行程 item。
- 双向联动：写入与当前相同的值不重复触发响应，避免 watch 循环。

---

### Task 1: 数据契约层（类型 + env 占位 + store 扩展）

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/stores/trip.ts`
- Modify: `frontend/.env.example`
- Modify: `frontend/.env`

**Interfaces:**
- Consumes: 后端 `final` 事件的 `day_plans`（结构见 `backend/app/graph/nodes/itinerary.py`）。
- Produces:
  - 类型 `LngLat`、`DayWeather`、`TripItem`、`DayPlan`。
  - store 新增 `activeDay: Ref<number|null>`、`activePoiId: Ref<string|null>`、`setActiveDay(d: number|null)`、`setActivePoi(id: string|null)`；`dayPlans` 类型收紧为 `DayPlan[]`；`setDayPlans(plans: DayPlan[])` 在非空时设 `activeDay=1`、清空时重置两个 active。

- [ ] **Step 1: 在 types/index.ts 新增行程数据类型并收紧 FinalPayload**

替换 `frontend/src/types/index.ts` 中的 `FinalPayload` 一行，并在文件末尾（`EventName` 之前）追加类型：

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

把原有的：

```ts
export interface FinalPayload { answer: string; day_plans?: any[] }
```

改为：

```ts
export interface FinalPayload { answer: string; day_plans?: DayPlan[] }
```

- [ ] **Step 2: 扩展 store 的联动状态与 action**

修改 `frontend/src/stores/trip.ts`：

1. 顶部 import 增加 `DayPlan`：

```ts
import type { ClarifyPayload, DayPlan } from '../types'
```

2. 把 `const dayPlans = ref<any[]>([])` 改为：

```ts
const dayPlans = ref<DayPlan[]>([])
const activeDay = ref<number | null>(null)
const activePoiId = ref<string | null>(null)
```

3. 把原 `const setDayPlans = (plans: any[]) => { dayPlans.value = plans }` 改为：

```ts
const setDayPlans = (plans: DayPlan[]) => {
  dayPlans.value = plans
  if (plans.length > 0) {
    activeDay.value = plans[0].day
    activePoiId.value = null
  } else {
    activeDay.value = null
    activePoiId.value = null
  }
}
const setActiveDay = (d: number | null) => { activeDay.value = d }
const setActivePoi = (id: string | null) => { activePoiId.value = id }
```

4. 在 `return { ... }` 中加入新成员：

```ts
  return {
    messages, agentProgress, nodeLabels, threadId, dayPlans, clarifyPending,
    activeDay, activePoiId,
    addMessage, appendToLastMessage, startNode, endNode, clearProgress,
    setThreadId, setClarify, clearClarify, setDayPlans, setActiveDay, setActivePoi,
  }
```

- [ ] **Step 3: env 增加高德 JS Key 占位**

`frontend/.env.example` 与 `frontend/.env` 各追加一行（`.env` 的值由你填真实 Key，没有就留空）：

```
VITE_AMAP_JS_KEY=
```

- [ ] **Step 4: 类型检查通过**

Run: `bun run build`
Expected: 构建成功，无 TS 报错（`dayPlans` 与 `FinalPayload` 已是 `DayPlan[]`，`useSSE.ts` 中 `setDayPlans((data as FinalPayload).day_plans || [])` 仍类型相容）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/stores/trip.ts frontend/.env.example frontend/.env
git commit -m "feat(m3): 行程数据强类型 + store 联动状态 + 高德 Key 占位"
```

---

### Task 2: useAMap composable（封装高德 SDK）

**Files:**
- Modify: `frontend/src/composables/useAMap.ts`

**Interfaces:**
- Consumes: `DayPlan` 类型（Task 1）；`import.meta.env.VITE_AMAP_JS_KEY`、可选 `VITE_AMAP_SECURITY_CODE`。
- Produces: `useAMap(containerRef: Ref<HTMLElement | null>)` 返回
  - `ready: Ref<boolean>`、`error: Ref<string | null>`
  - `init(): Promise<void>`（加载 SDK + 建图，需在容器挂载后调用）
  - `renderDayPlans(plans: DayPlan[], activeDay: number | null): void`
  - `focusPoi(poiId: string | null): void`
  - `onMarkerClick(cb: (poiId: string) => void): void`
  - `destroy(): void`

- [ ] **Step 1: 实现 useAMap composable**

整体替换 `frontend/src/composables/useAMap.ts`：

```ts
import { ref, type Ref } from 'vue'
import AMapLoader from '@amap/amap-jsapi-loader'
import type { DayPlan } from '../types'

// 按天配色（循环使用）
const DAY_COLORS = ['#409EFF', '#67C23A', '#E6A23C', '#F56C6C', '#909399', '#9B59B6']
const dayColor = (day: number) => DAY_COLORS[(day - 1) % DAY_COLORS.length]

export function useAMap(containerRef: Ref<HTMLElement | null>) {
  const ready = ref(false)
  const error = ref<string | null>(null)

  let AMap: any = null
  let map: any = null
  let infoWindow: any = null
  // poi_id -> { marker, item, day }
  const markerMap = new Map<string, { marker: any; name: string; day: number }>()
  let markerClickCb: ((poiId: string) => void) | null = null

  const init = async (): Promise<void> => {
    const key = import.meta.env.VITE_AMAP_JS_KEY as string | undefined
    if (!key) {
      error.value = '未配置高德地图 Key，请在 frontend/.env 设置 VITE_AMAP_JS_KEY'
      return
    }
    const securityCode = import.meta.env.VITE_AMAP_SECURITY_CODE as string | undefined
    if (securityCode) {
      ;(window as any)._AMapSecurityConfig = { securityJsCode: securityCode }
    }
    try {
      AMap = await AMapLoader.load({
        key,
        version: '2.0',
        plugins: ['AMap.InfoWindow'],
      })
      if (!containerRef.value) {
        error.value = '地图容器未就绪'
        return
      }
      map = new AMap.Map(containerRef.value, {
        zoom: 11,
        viewMode: '2D',
      })
      infoWindow = new AMap.InfoWindow({ offset: new AMap.Pixel(0, -30) })
      ready.value = true
    } catch (e: any) {
      error.value = '地图加载失败：' + (e?.message || String(e))
    }
  }

  const clearMarkers = () => {
    if (!map) return
    for (const { marker } of markerMap.values()) map.remove(marker)
    markerMap.clear()
  }

  const renderDayPlans = (plans: DayPlan[], activeDay: number | null): void => {
    if (!map || !AMap) return
    clearMarkers()
    if (infoWindow) infoWindow.close()
    const allMarkers: any[] = []
    for (const dp of plans) {
      const isActive = activeDay === null || dp.day === activeDay
      for (const item of dp.items) {
        const { lng, lat } = item.location
        if (typeof lng !== 'number' || typeof lat !== 'number') continue
        const color = dayColor(dp.day)
        const content =
          `<div class="amap-dot" style="background:${color};opacity:${isActive ? 1 : 0.35};" ` +
          `title="${item.name}"></div>`
        const marker = new AMap.Marker({
          position: [lng, lat],
          content,
          offset: new AMap.Pixel(-7, -7),
          zIndex: isActive ? 120 : 80,
        })
        marker.on('click', () => {
          if (markerClickCb) markerClickCb(item.poi_id)
        })
        map.add(marker)
        markerMap.set(item.poi_id, { marker, name: item.name, day: dp.day })
        allMarkers.push(marker)
      }
    }
    if (allMarkers.length > 0) map.setFitView(allMarkers, false, [60, 60, 60, 60])
  }

  const focusPoi = (poiId: string | null): void => {
    if (!map || !poiId) {
      if (infoWindow) infoWindow.close()
      return
    }
    const hit = markerMap.get(poiId)
    if (!hit) return
    const pos = hit.marker.getPosition()
    map.setCenter(pos)
    if (map.getZoom() < 13) map.setZoom(13)
    infoWindow.setContent(
      `<div style="padding:4px 8px;font-size:13px;font-weight:600;">${hit.name}</div>`,
    )
    infoWindow.open(map, pos)
  }

  const onMarkerClick = (cb: (poiId: string) => void): void => {
    markerClickCb = cb
  }

  const destroy = (): void => {
    clearMarkers()
    if (map) { map.destroy(); map = null }
    ready.value = false
  }

  return { ready, error, init, renderDayPlans, focusPoi, onMarkerClick, destroy }
}
```

- [ ] **Step 2: 类型检查通过**

Run: `bun run build`
Expected: 构建成功。`@amap/amap-jsapi-loader` 无官方类型，`AMap` 用 `any` 已规避；若报 `import.meta.env` 成员不存在，确认 `frontend/src/vite-env.d.ts` 存在 `/// <reference types="vite/client" />`（Vite 默认生成，通常已有）。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/composables/useAMap.ts
git commit -m "feat(m3): useAMap 封装高德 SDK（打点/聚焦/按天配色/加载守卫）"
```

---

### Task 3: MapView 渲染与联动响应

**Files:**
- Modify: `frontend/src/components/MapView.vue`

**Interfaces:**
- Consumes: `useAMap`（Task 2）、`tripStore.dayPlans`、`tripStore.activeDay`、`tripStore.activePoiId`、`tripStore.setActivePoi`（Task 1）。
- Produces: 一个铺满父容器的地图组件；`dayPlans`/`activeDay` 变化重绘打点，`activePoiId` 变化聚焦，marker 点击回写 `activePoiId`。

- [ ] **Step 1: 重写 MapView.vue**

整体替换 `frontend/src/components/MapView.vue`：

```vue
<template>
  <div class="map-view">
    <div ref="mapContainer" class="map-container"></div>
    <div v-if="amap.error.value" class="map-overlay">
      <el-icon :size="40" color="#909399"><Warning /></el-icon>
      <p>{{ amap.error.value }}</p>
    </div>
    <div v-else-if="tripStore.dayPlans.length === 0" class="map-overlay">
      <el-icon :size="40" color="#909399"><MapLocation /></el-icon>
      <p>生成行程后将在此打点</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { MapLocation, Warning } from '@element-plus/icons-vue'
import { useTripStore } from '../stores/trip'
import { useAMap } from '../composables/useAMap'

const tripStore = useTripStore()
const mapContainer = ref<HTMLElement | null>(null)
const amap = useAMap(mapContainer)

onMounted(async () => {
  await amap.init()
  amap.onMarkerClick((poiId) => tripStore.setActivePoi(poiId))
  if (amap.ready.value && tripStore.dayPlans.length > 0) {
    amap.renderDayPlans(tripStore.dayPlans, tripStore.activeDay)
  }
})

onBeforeUnmount(() => amap.destroy())

// day_plans 或 activeDay 变化 → 重绘打点（含按天配色焦点）
watch(
  () => [tripStore.dayPlans, tripStore.activeDay] as const,
  () => {
    if (amap.ready.value) amap.renderDayPlans(tripStore.dayPlans, tripStore.activeDay)
  },
  { deep: true },
)

// activePoiId 变化 → 地图聚焦
watch(
  () => tripStore.activePoiId,
  (id) => { if (amap.ready.value) amap.focusPoi(id) },
)
</script>

<style scoped>
.map-view {
  position: absolute;
  top: 0; left: 0;
  width: 100%; height: 100%;
}
.map-container { width: 100%; height: 100%; }
.map-overlay {
  position: absolute;
  inset: 0;
  background: #e8eaed;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #909399;
  text-align: center;
  padding: 24px;
}
.map-overlay p { margin: 0; font-size: 14px; }
</style>
```

- [ ] **Step 2: 在全局样式加入 marker 圆点样式**

高德自定义 marker 的 `content` HTML 不受 `scoped` 样式约束，需写到全局。在 `frontend/src/style.css` 末尾追加：

```css
/* 高德地图行程打点 */
.amap-dot {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
  cursor: pointer;
  box-sizing: border-box;
}
```

- [ ] **Step 3: 类型检查通过**

Run: `bun run build`
Expected: 构建成功。

- [ ] **Step 4: 手动验收（需真实 Key）**

填好 `VITE_AMAP_JS_KEY` 后 `bun run dev`，发起一次完整规划。
Expected:
- 配了 Key：收到 final 后地图自动打点并自适应视野；不同天颜色不同。
- 未配 Key：地图区显示"未配置高德地图 Key…"提示，应用不崩溃。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/MapView.vue frontend/src/style.css
git commit -m "feat(m3): MapView 真实地图打点 + 联动响应 + 加载守卫提示"
```

---

### Task 4: ResultPanel 悬浮行程面板 + App 布局

**Files:**
- Modify: `frontend/src/components/ResultPanel.vue`
- Modify: `frontend/src/App.vue`

**Interfaces:**
- Consumes: `tripStore.dayPlans`、`activeDay`、`activePoiId`、`setActiveDay`、`setActivePoi`（Task 1）。
- Produces: 右侧竖向悬浮、可收起的行程面板；Day Tab 切天写 `activeDay`，卡片点击写 `activePoiId`，`activePoiId` 命中卡片高亮并滚动可见。App 右侧改为地图铺满 + 面板悬浮。

- [ ] **Step 1: 重写 ResultPanel.vue**

整体替换 `frontend/src/components/ResultPanel.vue`：

```vue
<template>
  <div class="result-panel" :class="{ collapsed }">
    <button class="toggle-btn" @click="collapsed = !collapsed">
      {{ collapsed ? '行程 «' : '» 收起' }}
    </button>

    <div v-show="!collapsed" class="panel-body">
      <div v-if="tripStore.dayPlans.length === 0" class="empty">
        <p>行程生成后显示在这里</p>
      </div>

      <template v-else>
        <div class="day-tabs">
          <button
            v-for="dp in tripStore.dayPlans"
            :key="dp.day"
            class="day-tab"
            :class="{ active: dp.day === tripStore.activeDay }"
            @click="tripStore.setActiveDay(dp.day)"
          >
            Day {{ dp.day }}
          </button>
        </div>

        <div v-if="currentDay" class="day-meta">
          <span>{{ currentDay.weather.text }}</span>
          <span v-if="currentDay.weather.temp"> · {{ currentDay.weather.temp }}</span>
        </div>

        <div class="timeline">
          <div
            v-for="item in currentDay?.items || []"
            :key="item.poi_id"
            :ref="(el) => setItemRef(item.poi_id, el)"
            class="trip-card"
            :class="{ active: item.poi_id === tripStore.activePoiId }"
            @click="tripStore.setActivePoi(item.poi_id)"
          >
            <span class="card-icon">{{ item.type === 'meal' ? '🍴' : '📍' }}</span>
            <div class="card-text">
              <div class="card-name">{{ item.name }}</div>
              <div v-if="item.type === 'attraction' && item.indoor" class="card-tag">室内</div>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { useTripStore } from '../stores/trip'

const tripStore = useTripStore()
const collapsed = ref(false)

const currentDay = computed(() =>
  tripStore.dayPlans.find((d) => d.day === tripStore.activeDay) || null,
)

const itemRefs = new Map<string, HTMLElement>()
const setItemRef = (poiId: string, el: unknown) => {
  if (el) itemRefs.set(poiId, el as HTMLElement)
  else itemRefs.delete(poiId)
}

// activePoiId 命中当前面板的卡片 → 滚动可见
watch(
  () => tripStore.activePoiId,
  async (id) => {
    if (!id) return
    await nextTick()
    itemRefs.get(id)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  },
)
</script>

<style scoped>
.result-panel {
  position: absolute;
  top: 16px;
  right: 16px;
  bottom: 16px;
  width: 300px;
  background: rgba(255, 255, 255, 0.96);
  border-radius: 12px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.12);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width 0.2s ease;
}
.result-panel.collapsed {
  width: auto;
}
.toggle-btn {
  flex-shrink: 0;
  border: none;
  background: #f4f4f5;
  color: #606266;
  font-size: 12px;
  padding: 8px 12px;
  cursor: pointer;
  text-align: right;
}
.toggle-btn:hover { background: #ecf5ff; color: #409eff; }
.panel-body { flex: 1; overflow-y: auto; padding: 8px 12px 12px; }
.empty { color: #909399; font-size: 13px; text-align: center; padding: 24px 0; }
.day-tabs { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.day-tab {
  border: 1px solid #dcdfe6;
  background: #fff;
  color: #606266;
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
}
.day-tab.active { background: #409eff; color: #fff; border-color: #409eff; }
.day-meta { font-size: 12px; color: #909399; margin-bottom: 8px; }
.timeline { display: flex; flex-direction: column; gap: 8px; }
.trip-card {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.trip-card:hover { border-color: #c6e2ff; }
.trip-card.active {
  border-color: #409eff;
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.2);
}
.card-icon { font-size: 16px; line-height: 1.4; }
.card-text { flex: 1; min-width: 0; }
.card-name { font-size: 14px; color: #303133; font-weight: 500; }
.card-tag {
  display: inline-block;
  margin-top: 4px;
  font-size: 11px;
  color: #67c23a;
  background: #f0f9eb;
  border-radius: 4px;
  padding: 1px 6px;
}
</style>
```

- [ ] **Step 2: 调整 App.vue 右侧为地图铺满 + 面板悬浮**

确认 `frontend/src/App.vue` 中右侧内容区结构。把当前的右侧容器（同时含 ChatPanel 与 ResultPanel 的上下/并列布局）改为：左侧 ChatPanel 不变，右侧容器 `position: relative` 内同时放 `<MapView />`（铺满）与 `<ResultPanel />`（绝对悬浮）。

模板中右侧区域改为：

```vue
      <div class="map-area">
        <MapView />
        <ResultPanel />
      </div>
```

确保引入了组件：

```ts
import MapView from './components/MapView.vue'
import ResultPanel from './components/ResultPanel.vue'
```

并在 `<style>` 中确保 `.map-area` 撑满右侧且为定位上下文：

```css
.map-area {
  position: relative;
  flex: 1;
  min-width: 0;
  height: 100%;
  overflow: hidden;
}
```

（注：左侧 ChatPanel 容器宽度保持现状；若现有类名不同，按现有布局把右侧从原 ResultPanel 占位替换为上述 `.map-area`。移除原 `v-if="false"` 的 PlannerLayout 残留与上下分栏样式。）

- [ ] **Step 3: 类型检查通过**

Run: `bun run build`
Expected: 构建成功。注意 `setItemRef` 的函数式 ref 返回 `void`，模板 `:ref="(el) => setItemRef(...)"` 类型相容。

- [ ] **Step 4: 手动验收**

`bun run dev`，生成行程后：
Expected:
- 右侧地图铺满，行程面板悬浮右缘；Day Tab 可切天，地图打点焦点随之变化。
- 点击卡片 → 卡片高亮 + 地图平移高亮 + InfoWindow。
- "» 收起" → 面板收成窄按钮，地图视野最大化；"行程 «" 可展开。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ResultPanel.vue frontend/src/App.vue
git commit -m "feat(m3): 右侧地图铺满 + 悬浮可收起行程面板 + 卡片联动"
```

---

### Task 5: 双向联动端到端验收

**Files:**
- 无新增；验证 Task 1–4 协同。

**Interfaces:**
- Consumes: 全部既有联动状态与组件。
- Produces: 通过验收的 M3 完整闭环。

- [ ] **Step 1: 完整类型检查与构建**

Run: `bun run build`
Expected: 构建成功，无 TS 错误。

- [ ] **Step 2: 端到端手动验收（配真实 Key）**

`bun run dev`，跑通策划书 M3 验收路径：

1. 发起完整规划 → 收到 final → 地图自动打点并 `setFitView`，面板默认显示 Day1。
2. 点击某张行程卡片 → 地图平移到该点 + InfoWindow + 卡片高亮。
3. 点击地图上某个 marker → 对应卡片高亮并 `scrollIntoView`（反向联动）。
4. 切 Day Tab → marker 按天配色焦点切换、面板内容切当天。
5. 收起/展开面板正常，地图不被遮挡时视野最大化。
6. 反复点击同一卡片/marker 不报错、无 watch 循环（控制台无异常刷屏）。

- [ ] **Step 3: Key 缺失降级验收**

临时清空 `VITE_AMAP_JS_KEY` 重启 dev。
Expected: 地图区显示配置提示，行程面板仍可正常切天/看卡片，应用不崩溃。

- [ ] **Step 4: 更新里程碑文档（如有验收清单）**

若 `backend/README.md` 或根目录有 M3 验收清单，勾选对应项。无则跳过。

- [ ] **Step 5: Commit（如 Step 4 有改动）**

```bash
git add -A
git commit -m "docs(m3): 勾选 M3 验收清单"
```

---

## 任务依赖

Task 1 → 2 → 3 → 4 → 5 线性依赖（后者消费前者的接口）。建议顺序执行。
