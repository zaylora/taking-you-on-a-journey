<template>
  <div class="chat-panel">
    <div class="header">
      <h2>AI 旅游助手</h2>
      <el-button size="small" type="primary" plain @click="newConversation">新建会话</el-button>
    </div>
    <div class="session-list" v-if="tripStore.conversations.length > 0">
      <button
        v-for="conversation in tripStore.conversations"
        :key="conversation.threadId"
        class="session-item"
        :class="{ active: conversation.threadId === tripStore.activeThreadId }"
        @click="switchConversation(conversation.threadId)"
      >
        <span class="session-title">{{ conversation.title }}</span>
      </button>
    </div>
    <MessageList :messages="tripStore.messages" :loading="loading" />
    <div class="quick-prompts" v-if="!loading && tripStore.messages.length > 0">
      <el-tag round type="info" class="prompt-chip" @click="send('预算大概多少？')">预算大概多少？</el-tag>
      <el-tag round type="info" class="prompt-chip" @click="send('推荐一些当地美食')">推荐一些当地美食</el-tag>
      <el-tag round type="info" class="prompt-chip" @click="send('调整为 7 天行程')">调整为 7 天行程</el-tag>
    </div>
    <ChatInput :loading="loading" @send="send" @abort="abort" />
  </div>
</template>

<script setup lang="ts">
import { useTripStore } from '../stores/trip'
import { useSSE } from '../composables/useSSE'
import MessageList from './MessageList.vue'
import ChatInput from './ChatInput.vue'

const tripStore = useTripStore()
const { loading, send, abort } = useSSE()

const newConversation = async () => {
  if (loading.value) return
  await tripStore.createConversation()
}

const switchConversation = async (threadId: string) => {
  if (loading.value || threadId === tripStore.activeThreadId) return
  await tripStore.loadConversation(threadId)
}
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
.session-list {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding: 10px 12px;
  border-bottom: 1px solid #ebeef5;
  background: #fafafa;
}
.session-item {
  flex: 0 0 auto;
  max-width: 150px;
  border: 1px solid #dcdfe6;
  background: #fff;
  color: #606266;
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 12px;
  cursor: pointer;
}
.session-item.active {
  color: #409eff;
  border-color: #409eff;
  background: #ecf5ff;
}
.session-title {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
