<template>
  <div class="agent-progress">
    <div v-if="entries.length" class="progress-bar">
      <el-tag
        v-for="[node, status] in entries"
        :key="node"
        :type="status === 'done' ? 'success' : 'primary'"
        :effect="status === 'done' ? 'plain' : 'dark'"
        size="small"
        class="node-tag"
      >
        {{ status === 'running' ? '正在' : '' }}{{ labelOf(node) }}{{ status === 'running' ? '...' : '' }}
      </el-tag>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useTripStore } from '../stores/trip'

const LABELS: Record<string, string> = {
  clarify: '理解需求', dispatch: '梳理要点', weather: '查询天气',
  attractions: '检索景点', restaurants: '挑选餐厅', transport: '规划交通',
  itinerary: '编排行程', summarize: '生成攻略',
}
const tripStore = useTripStore()
const entries = computed(() => Object.entries(tripStore.agentProgress))
// 优先展示后端 node_start 携带的 label，无则回退本地映射
const labelOf = (n: string) => tripStore.nodeLabels[n] || LABELS[n] || n
</script>

<style scoped>
.agent-progress { padding: 4px 0; min-height: 24px; }
.progress-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.node-tag { transition: all .3s; }
</style>