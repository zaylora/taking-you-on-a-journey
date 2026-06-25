<template>
  <div class="agent-progress">
    <!-- 思考过程（仅推理模型有 reasoning_content 时出现），默认折叠 -->
    <div v-if="tripStore.thinkingText" class="thinking-block">
      <div class="thinking-head" @click="thinkingOpen = !thinkingOpen">
        <span class="thinking-icon">💭</span>
        <span class="thinking-title">思考过程</span>
        <span class="thinking-toggle">{{ thinkingOpen ? '收起' : '展开' }}</span>
      </div>
      <div v-show="thinkingOpen" class="thinking-body">{{ tripStore.thinkingText }}</div>
    </div>

    <!-- 工具调用过程链：调了哪个工具、是否完成 -->
    <transition-group name="slide-fade" tag="div" class="progress-bar">
      <div
        v-for="(step, idx) in tripStore.toolSteps"
        :key="step.tool + '-' + idx"
        class="node-pill"
        :class="{ done: step.status === 'done' }"
      >
        <span v-if="step.status === 'running'" class="loading-icon"></span>
        <span v-else class="done-icon">✓</span>
        <span class="node-label">{{ step.status === 'done' ? '已' : '正在' }}{{ step.label }}</span>
      </div>

      <!-- 工具链尚为空但 agent 在跑时，兜底显示"正在思考" -->
      <div v-if="tripStore.toolSteps.length === 0 && thinking" key="__thinking__" class="node-pill">
        <span class="loading-icon"></span>
        <span class="node-label">正在思考…</span>
      </div>
    </transition-group>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useTripStore } from '../stores/trip'

const tripStore = useTripStore()
const thinkingOpen = ref(false)

// 是否有节点在运行（model/tools），用于工具链为空时的兜底文案
const thinking = computed(() =>
  Object.values(tripStore.agentProgress).some((s) => s !== 'done'),
)
</script>

<style scoped>
.agent-progress {
  min-height: 24px;
  padding: 4px 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.progress-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  position: relative;
}

/* 思考过程折叠块 */
.thinking-block {
  border: 1px solid var(--el-border-color-lighter, #e4e7ed);
  border-radius: 10px;
  background: var(--el-fill-color-blank, #fff);
  overflow: hidden;
}
.thinking-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  cursor: pointer;
  font-size: 13px;
  color: var(--el-text-color-regular, #606266);
  user-select: none;
}
.thinking-head:hover { background: var(--el-fill-color-light, #f4f4f5); }
.thinking-title { font-weight: 500; }
.thinking-toggle { margin-left: auto; font-size: 12px; color: var(--el-color-primary, #409eff); }
.thinking-body {
  padding: 8px 12px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary, #909399);
  white-space: pre-wrap;
  word-break: break-word;
  border-top: 1px dashed var(--el-border-color-lighter, #e4e7ed);
  max-height: 220px;
  overflow-y: auto;
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
