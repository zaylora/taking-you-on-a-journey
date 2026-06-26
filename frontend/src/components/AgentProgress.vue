<template>
  <div class="agent-progress">
    <!-- 工具调用过程链：调了哪个工具、是否完成，垂直排列 -->
    <transition-group name="slide-fade" tag="div" class="progress-bar">
      <div
        v-for="(step, idx) in toolSteps"
        :key="step.tool + '-' + idx"
        class="node-pill"
        :class="{ done: step.status === 'done' }"
      >
        <span v-if="step.status === 'running'" class="loading-icon"></span>
        <span v-else class="done-icon">✓</span>
        <span class="node-label">{{ step.status === 'done' ? '已' : '正在' }}{{ step.label }}</span>
      </div>
    </transition-group>
  </div>
</template>

<script setup lang="ts">
import type { ToolStep } from '../stores/trip'

withDefaults(defineProps<{
  toolSteps?: ToolStep[]
}>(), {
  toolSteps: () => [],
})
</script>

<style scoped>
.agent-progress {
  padding: 4px 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.progress-bar {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
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
  transition: opacity 0.3s ease;
}
.node-pill.done {
  opacity: 0.7;
  background-color: var(--el-color-success-light-9, #f0f9eb);
  border-color: var(--el-color-success-light-7, #e1f3d8);
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
.done-icon {
  width: 12px;
  height: 12px;
  margin-right: 8px;
  color: var(--el-color-success, #67c23a);
  font-weight: bold;
  line-height: 12px;
  text-align: center;
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
