<template>
  <div class="agent-progress">
    <div v-if="activeNodes.length > 0" class="progress-bar">
      <span>执行中: </span>
      <el-tag
        v-for="node in activeNodes"
        :key="node"
        type="primary"
        effect="dark"
        size="small"
        class="node-tag"
      >
        {{ node }}
      </el-tag>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useTripStore } from '../stores/trip'

const tripStore = useTripStore()
const activeNodes = computed(() => tripStore.agentProgress)
</script>

<style scoped>
.agent-progress {
  padding: 8px 0;
  min-height: 24px;
}
.progress-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #666;
}
.node-tag {
  animation: pulse 1.5s infinite;
}

@keyframes pulse {
  0% { opacity: 0.7; }
  50% { opacity: 1; }
  100% { opacity: 0.7; }
}
</style>
