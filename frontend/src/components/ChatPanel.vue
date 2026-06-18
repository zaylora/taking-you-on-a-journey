<template>
  <div class="chat-panel">
    <div class="header">
      <h2>AI 旅游助手</h2>
    </div>
    <MessageList :messages="tripStore.messages" :loading="loading" />
    <div class="quick-prompts" v-if="!loading && tripStore.messages.length > 0">
      <el-tag round type="info" class="prompt-chip" @click="send('预算大概多少？')">预算大概多少？</el-tag>
      <el-tag round type="info" class="prompt-chip" @click="send('推荐一些当地美食')">推荐一些当地美食</el-tag>
      <el-tag round type="info" class="prompt-chip" @click="send('调整为 7 天行程')">调整为 7 天行程</el-tag>
    </div>
    <ClarifyOptions :send="send" />
    <ChatInput :loading="loading" @send="send" @abort="abort" />
  </div>
</template>

<script setup lang="ts">
import { useTripStore } from '../stores/trip'
import { useSSE } from '../composables/useSSE'
import MessageList from './MessageList.vue'
import ChatInput from './ChatInput.vue'
import ClarifyOptions from './ClarifyOptions.vue'

const tripStore = useTripStore()
const { loading, send, abort } = useSSE()
</script>

<style scoped>
.chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #fff;
  border-right: 1px solid #ebeef5;
}
.header {
  padding: 16px;
  border-bottom: 1px solid #ebeef5;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header h2 {
  margin: 0;
  font-size: 18px;
  color: #303133;
}
.quick-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 0 16px 12px 16px;
}
.prompt-chip {
  cursor: pointer;
  background-color: #f4f4f5;
  border-color: #e9e9eb;
  color: #909399;
}
.prompt-chip:hover {
  background-color: #ecf5ff;
  color: #409eff;
}
</style>