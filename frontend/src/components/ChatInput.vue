<template>
  <div class="chat-input-container">
    <el-input
      v-model="inputMsg"
      type="textarea"
      :rows="3"
      resize="none"
      placeholder="在此输入您的行程需求..."
      @keydown.enter.prevent="handleSend"
    />
    <div class="actions">
      <el-button v-if="loading" @click="emit('abort')">停止</el-button>
      <el-button type="primary" :loading="loading" @click="handleSend">
        发送
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  loading: boolean
}>()

const emit = defineEmits<{
  (e: 'send', msg: string): void
  (e: 'abort'): void
}>()

const inputMsg = ref('')

const handleSend = () => {
  if (!inputMsg.value.trim() || props.loading) return
  emit('send', inputMsg.value)
  inputMsg.value = ''
}
</script>

<style scoped>
.chat-input-container {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px;
  border-top: 1px solid #ebeef5;
  background-color: #fff;
}
.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
