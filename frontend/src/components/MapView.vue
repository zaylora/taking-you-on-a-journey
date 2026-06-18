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

// activeTransport 变化 → 绘制路线
watch(
  () => tripStore.activeTransport,
  (transportItem) => {
    if (!amap.ready.value) return
    if (!transportItem) {
      amap.clearRoute()
      return
    }

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

    if (startLoc && endLoc) {
      amap.drawRoute(startLoc, endLoc, transportItem.mode)
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
