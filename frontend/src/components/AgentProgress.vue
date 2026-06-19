<template>
  <div class="agent-progress">
    <transition-group name="slide-fade" tag="div" class="progress-bar">
      <div
        v-for="[node] in activeEntries"
        :key="node"
        class="node-pill"
      >
        <span class="loading-icon"></span>
        <span class="node-label">{{ labelOf(node) }}</span>
      </div>
    </transition-group>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useTripStore } from '../stores/trip'

const tripStore = useTripStore()

const LABELS: Record<string, string> = {
  clarify: '正在理解你的需求…',
  memory: '正在读取会话上下文…',
  dispatch_agent: '正在判断任务并分发…',
  retrieve: '正在并行检索…',
  weather: '正在查询目的地天气…',
  attractions: '正在检索热门景点…',
  restaurants: '正在挑选餐厅…',
  transport: '正在规划交通…',
  itinerary: '正在按顺路编排每日行程…',
  refine: '正在局部调整行程…',
  answer: '正在基于当前方案回答…',
  accommodation: '正在挑选住宿…',
  budget: '正在核算预算…',
  summarize: '正在生成攻略…',
  memory_update: '正在保存会话记忆…',
}

const activeEntries = computed(() => {
  return Object.entries(tripStore.agentProgress).filter(([_, status]) => status !== 'done')
})

const labelOf = (n: string) => tripStore.nodeLabels[n] || LABELS[n] || n

</script>

<style scoped>
.agent-progress { 
  min-height: 24px; 
  padding: 4px 0;
}
.progress-bar { 
  display: flex; 
  align-items: center; 
  gap: 10px; 
  flex-wrap: wrap; 
  position: relative;
}

/* 从下往上渐显动画 */
.slide-fade-enter-active,
.slide-fade-leave-active {
  transition: all 0.5s cubic-bezier(0.25, 0.8, 0.25, 1);
}
.slide-fade-enter-from {
  opacity: 0;
  transform: translateY(15px);
}
.slide-fade-leave-to {
  opacity: 0;
  transform: translateY(-10px) scale(0.95);
}
.slide-fade-move {
  transition: transform 0.4s ease;
}

/* Codex style pill */
.node-pill {
  display: inline-flex;
  align-items: center;
  padding: 6px 14px;
  background-color: var(--el-fill-color-light, #f4f4f5);
  border: 1px solid var(--el-border-color-lighter, #e4e7ed);
  border-radius: 20px;
  font-size: 13px;
  color: var(--el-text-color-regular, #606266);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.loading-icon {
  width: 12px;
  height: 12px;
  margin-right: 8px;
  border: 2px solid var(--el-color-primary, #409eff);
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.node-label {
  line-height: 1;
  font-weight: 500;
}
</style>
