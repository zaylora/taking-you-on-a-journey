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
        <div v-if="tripStore.budget" class="budget-bar" :class="{ over: tripStore.budget.over }">
          <div class="budget-head">
            <span class="budget-total">已估 ¥{{ tripStore.budget.estimated }}</span>
            <span v-if="tripStore.budget.limit > 0" class="budget-limit">
              / 预算 ¥{{ tripStore.budget.limit }}
            </span>
          </div>
          <div v-if="tripStore.budget.over" class="budget-warn">
            ⚠ 超支 ¥{{ Math.round(tripStore.budget.estimated - tripStore.budget.limit) }}
            （已自动重排 {{ tripStore.budget.retry_count }} 次）
          </div>
          <div v-if="tripStore.budget.note" class="budget-note">{{ tripStore.budget.note }}</div>
          <div class="budget-breakdown">
            <span>门票 ¥{{ tripStore.budget.breakdown.ticket }}</span>
            <span>住宿 ¥{{ tripStore.budget.breakdown.hotel }}</span>
            <span>餐饮 ¥{{ tripStore.budget.breakdown.food }}</span>
            <span>交通 ¥{{ tripStore.budget.breakdown.transport }}</span>
          </div>
        </div>

        <div class="day-tabs">
          <button
            class="day-tab"
            :class="{ active: tripStore.activeDay === null }"
            @click="tripStore.setActiveDay(null)"
          >
            总览
          </button>
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

        <template v-for="day in (tripStore.activeDay === null ? tripStore.dayPlans : (currentDay ? [currentDay] : []))" :key="day.day">
          <div class="day-meta" :style="{ marginTop: tripStore.activeDay === null ? '12px' : '0' }">
            <span v-if="tripStore.activeDay === null" style="font-weight: 600; margin-right: 8px; color: #303133;">Day {{ day.day }}</span>
            <span>{{ day.weather.text }}</span>
            <span v-if="day.weather.temp"> · {{ day.weather.temp }}</span>
          </div>

          <div class="timeline">
            <template v-for="(item, idx) in (day.items || []).filter(i => i.type === 'transport' || i.name)" :key="item.poi_id || idx">
            <!-- 交通条目：显示为紧凑连接行 -->
            <div
              v-if="item.type === 'transport'"
              class="trip-card transport-card"
              :class="{ active: item === tripStore.activeTransport }"
              @click="tripStore.setActiveTransport(item)"
            >
              <span class="card-icon">🚌</span>
              <div class="card-text">
                <div class="card-name transport-name">
                  {{ item.from }} → {{ item.to }}
                </div>
                <div class="card-sub">
                  <div style="display:flex; align-items:center; flex-wrap:wrap; gap:4px;">
                    <span @click.stop>
                      <el-select
                        v-model="item.mode"
                        size="small"
                        class="transport-el-select"
                      >
                        <el-option label="公交/地铁" value="公交/地铁" />
                        <el-option label="打车" value="打车" />
                        <el-option label="驾车" value="驾车" />
                        <el-option label="步行" value="步行" />
                        <el-option label="骑行" value="骑行" />
                      </el-select>
                    </span>
                    <span v-if="item.cost" class="card-cost" style="margin-right:8px;">¥{{ item.cost }}/人</span>
                    <span v-if="item.routeInfo" style="font-size:11px; color:#909399;">
                      {{ formatDistance(item.routeInfo.distance) }} · 约{{ formatTime(item.routeInfo.time) }}
                    </span>
                  </div>
                </div>
              </div>
            </div>
            <!-- 景点 / 餐饮条目 -->
            <div
              v-else
              :ref="(el) => setItemRef(item.poi_id, el)"
              class="trip-card"
              :class="{ active: item.poi_id === tripStore.activePoiId }"
              @click="tripStore.setActivePoi(item.poi_id)"
            >
              <span class="card-icon">{{ item.type === 'meal' ? '🍴' : '📍' }}</span>
              <div class="card-text">
                <div class="card-name">{{ item.name }}</div>
                <div class="card-sub">
                  <span v-if="item.type === 'attraction' && item.indoor" class="card-tag">室内</span>
                  <span v-if="item.cost" class="card-cost">¥{{ item.cost }}/人</span>
                </div>
              </div>
            </div>
          </template>

          <div
            v-if="day.hotel"
            class="trip-card hotel-card"
            :class="{ active: day.hotel.poi_id === tripStore.activePoiId }"
            @click="tripStore.setActivePoi(day.hotel.poi_id)"
          >
            <span class="card-icon">🏨</span>
            <div class="card-text">
              <div class="card-name">{{ day.hotel.name }}</div>
              <div class="card-sub">
                <span v-if="day.hotel.level" class="card-tag hotel-tag">{{ day.hotel.level }}</span>
                <span class="card-cost">¥{{ day.hotel.price }}/晚</span>
              </div>
            </div>
          </div>
        </div>
      </template>
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

const formatDistance = (meters: number) => {
  if (!meters) return ''
  if (meters < 1000) return `${meters}米`
  return `${(meters / 1000).toFixed(1)}公里`
}

const formatTime = (seconds: number) => {
  if (!seconds) return ''
  if (seconds < 60) return `${seconds}秒`
  const mins = Math.floor(seconds / 60)
  if (mins < 60) return `${mins}分钟`
  const hours = Math.floor(mins / 60)
  const rem = mins % 60
  return `${hours}小时${rem}分钟`
}
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

.budget-bar {
  background: #f4f9f0;
  border: 1px solid #e1f3d8;
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 10px;
}
.budget-bar.over { background: #fef0f0; border-color: #fde2e2; }
.budget-head { font-size: 14px; font-weight: 600; color: #303133; }
.budget-limit { color: #909399; font-weight: 400; font-size: 12px; }
.budget-warn { margin-top: 4px; font-size: 12px; color: #f56c6c; font-weight: 600; }
.budget-note { margin-top: 4px; font-size: 12px; color: #e6a23c; }
.budget-breakdown {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  margin-top: 6px;
  font-size: 11px;
  color: #606266;
}

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
.hotel-card { cursor: pointer; background: #fafcff; border-color: #e6eefb; }
.hotel-card:hover { border-color: #c6e2ff; }
.hotel-card.active { border-color: #409eff; box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.2); }
.transport-card {
  cursor: pointer;
  background: #f9f9fb;
  border-color: #ebebf0;
  padding: 6px 10px;
  opacity: 0.85;
}
.transport-card:hover { border-color: #c6e2ff; }
.transport-name { font-size: 12px; color: #606266; font-weight: 400; }
.transport-tag { color: #909399; background: #f4f4f5; }
.card-icon { font-size: 16px; line-height: 1.4; }
.card-text { flex: 1; min-width: 0; }
.card-name { font-size: 14px; color: #303133; font-weight: 500; }
.card-sub { display: flex; align-items: center; gap: 6px; margin-top: 4px; }
.card-tag {
  display: inline-block;
  font-size: 11px;
  color: #67c23a;
  background: #f0f9eb;
  border-radius: 4px;
  padding: 1px 6px;
}
.hotel-tag { color: #409eff; background: #ecf5ff; }
.card-cost { font-size: 12px; color: #e6a23c; font-weight: 600; }
.transport-el-select {
  width: 95px;
  margin-right: 6px;
}
.transport-el-select :deep(.el-select__wrapper) {
  background-color: #f0f9eb;
  box-shadow: none !important;
  padding: 2px 8px;
  min-height: 22px;
  border-radius: 4px;
}
.transport-el-select :deep(.el-select__placeholder) {
  color: #67c23a;
  font-size: 11px;
}
</style>
