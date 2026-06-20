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
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
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
    updateOverviewRoute()
  }
})

const updateOverviewRoute = () => {
  if (!amap.ready.value) return
  if (tripStore.activePoiId || tripStore.activeTransport) {
    amap.clearOverviewRoute()
  } else {
    if (tripStore.activeDay === null) {
      amap.drawOverviewRoute(buildOverviewLegs(tripStore.dayPlans))
    } else {
      const currentDayPlan = tripStore.dayPlans.find(dp => dp.day === tripStore.activeDay)
      if (currentDayPlan) amap.drawOverviewRoute(buildOverviewLegs([currentDayPlan]))
      else amap.clearOverviewRoute()
    }
  }
}

onBeforeUnmount(() => amap.destroy())

// 地图指纹：只汇集影响打点与路线的字段（天数、各点位坐标），不含交通段的 routeInfo。
// 这样预取路程信息时不会触发地图重绘，消除预取期间反复重绘的抖动与重复请求高德。
const mapSignature = computed(() => {
  const parts: string[] = [`active:${tripStore.activeDay}`]
  for (const dp of tripStore.dayPlans) {
    parts.push(`day:${dp.day}`)
    for (const item of dp.items) {
      if (item.type === 'transport') continue
      parts.push(`${item.poi_id}@${item.location?.lng},${item.location?.lat}`)
    }
    if (dp.hotel) parts.push(`hotel:${dp.hotel.poi_id}@${dp.hotel.location?.lng},${dp.hotel.location?.lat}`)
  }
  return parts.join('|')
})

// 点位/天数变化 → 重绘打点（含按天配色焦点）与总览路线
watch(mapSignature, () => {
  if (amap.ready.value) {
    amap.renderDayPlans(tripStore.dayPlans, tripStore.activeDay)
    updateOverviewRoute()
  }
})

// activePoiId 变化 → 地图聚焦，并隐藏/恢复总览路线
watch(
  () => tripStore.activePoiId,
  (id) => {
    if (amap.ready.value) {
      amap.focusPoi(id)
      updateOverviewRoute()
    }
  },
)

// 交通方式变化 → 重绘分段总览路线。
// 单列一个指纹（只含交通段的 mode），避免并入 mapSignature 触发打点重渲染与预取抖动。
// 总览态外（选中点位/单段）updateOverviewRoute 会自行 clear，互不干扰。
const overviewModeSignature = computed(() => {
  const parts: string[] = []
  for (const dp of tripStore.dayPlans) {
    for (const item of dp.items) {
      if (item.type === 'transport') parts.push(`${item.from}>${item.to}:${item.mode}`)
    }
  }
  return parts.join('|')
})
watch(overviewModeSignature, () => {
  if (amap.ready.value) updateOverviewRoute()
})

const getTransportLocations = (transportItem: any) => {
  let startLoc = null
  let endLoc = null
  for (const dp of tripStore.dayPlans) {
    const idx = dp.items.indexOf(transportItem)
    if (idx !== -1) {
      if (idx > 0) {
        startLoc = dp.items[idx - 1].location
      } else {
        const prevDay = tripStore.dayPlans.find(d => d.day === dp.day - 1)
        if (prevDay && prevDay.hotel) startLoc = prevDay.hotel.location
      }
      
      if (idx < dp.items.length - 1) {
        endLoc = dp.items[idx + 1].location
      } else if (dp.hotel) {
        endLoc = dp.hotel.location
      }
      break
    }
  }
  return { startLoc, endLoc }
}

// 把若干天的行程拆成「分段总览路线」：每个交通段一条 leg，带自己的 mode。
// 复用 getTransportLocations（按全局 dayPlans 定位起讫），单天/全天通用。
const buildOverviewLegs = (plans: any[]) => {
  const legs: Array<{ start: any; end: any; mode?: string }> = []
  for (const dp of plans) {
    for (const item of dp.items) {
      if (item.type !== 'transport') continue
      const { startLoc, endLoc } = getTransportLocations(item)
      if (startLoc && endLoc) legs.push({ start: startLoc, end: endLoc, mode: item.mode })
    }
  }
  return legs
}

const prefetchRouteInfos = async () => {
  for (const dp of tripStore.dayPlans) {
    for (const item of dp.items) {
      if (item.type === 'transport' && !item.routeInfo) {
        const { startLoc, endLoc } = getTransportLocations(item)
        if (startLoc && endLoc) {
          const info = await amap.fetchRouteInfo(startLoc, endLoc, item.mode)
          if (info) item.routeInfo = info
          await new Promise(r => setTimeout(r, 200)) // 防高并发
        }
      }
    }
  }
}

// 预取也改挂在地图指纹上：只有点位变化（新行程/改点）才重新预取，
// routeInfo 写入不再反过来重启预取，避免重复请求。
watch(
  () => [mapSignature.value, amap.ready.value] as const,
  ([, ready]) => {
    if (ready && tripStore.dayPlans.length > 0) {
      prefetchRouteInfos()
    }
  },
  { immediate: true }
)

// activeTransport 变化 → 绘制路线
watch(
  () => [tripStore.activeTransport, tripStore.activeTransport?.mode] as const,
  ([transportItem]) => {
    if (!amap.ready.value) return
    if (!transportItem) {
      amap.clearRoute()
      updateOverviewRoute()
      return
    }

    updateOverviewRoute() // Hides the overview route because activeTransport is set

    const { startLoc, endLoc } = getTransportLocations(transportItem)

    if (startLoc && endLoc) {
      amap.drawRoute(startLoc, endLoc, transportItem.mode, (info) => {
        // 避免 deep: true 导致的无限循环，这里明确只监听 item 和 mode 的变化
        transportItem.routeInfo = info
      })
    } else {
      console.warn('无法解析此交通路线的起点或终点坐标')
    }
  }
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
