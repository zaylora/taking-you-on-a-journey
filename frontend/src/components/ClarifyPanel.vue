<template>
  <transition name="clarify-pop">
    <div v-if="clarify" class="clarify-panel">
      <div class="clarify-head">
        <span class="clarify-question">{{ clarify.question }}</span>
        <el-icon class="clarify-close" @click="close"><Close /></el-icon>
      </div>
      <div class="clarify-options">
        <el-button
          v-for="option in clarify.options"
          :key="option"
          size="small"
          plain
          :disabled="loading"
          @click="choose(option)"
        >{{ option }}</el-button>
      </div>
      <div class="clarify-custom">
        <el-input
          v-model="custom"
          size="small"
          placeholder="或填写其它答案…"
          :disabled="loading"
          @keydown.enter.prevent="submitCustom"
        />
        <el-button size="small" type="primary" :disabled="!custom.trim() || loading" @click="submitCustom">
          提交
        </el-button>
      </div>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Close } from '@element-plus/icons-vue'
import { useTripStore } from '../stores/trip'

const props = defineProps<{ loading: boolean }>()
const emit = defineEmits<{ (e: 'answer', text: string): void }>()

const tripStore = useTripStore()
const clarify = computed(() => tripStore.pendingClarify)
const custom = ref('')

const close = () => tripStore.setPendingClarify(null)

const choose = (option: string) => {
  if (props.loading) return
  tripStore.setPendingClarify(null)
  emit('answer', option)
}

const submitCustom = () => {
  const text = custom.value.trim()
  if (!text || props.loading) return
  custom.value = ''
  tripStore.setPendingClarify(null)
  emit('answer', text)
}
</script>

<style scoped>
.clarify-panel {
  position: absolute;
  left: 16px; right: 16px; bottom: 100%;
  margin-bottom: 8px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 10px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.12);
  padding: 12px 14px;
  z-index: 20;
}
.clarify-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
.clarify-question { font-size: 14px; color: #303133; font-weight: 500; line-height: 1.4; }
.clarify-close { cursor: pointer; color: #909399; flex-shrink: 0; margin-top: 2px; }
.clarify-options { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }
.clarify-custom { display: flex; gap: 8px; }

/* 从下往上弹出 */
.clarify-pop-enter-active, .clarify-pop-leave-active { transition: all 0.25s cubic-bezier(0.25, 0.8, 0.25, 1); }
.clarify-pop-enter-from, .clarify-pop-leave-to { opacity: 0; transform: translateY(16px); }
</style>
