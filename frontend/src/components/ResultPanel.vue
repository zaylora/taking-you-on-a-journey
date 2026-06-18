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
