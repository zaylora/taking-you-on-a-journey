<template>
  <div class="message-list" ref="listRef">
    <div
      v-for="(msg, index) in messages"
      :key="index"
      :class="['message', msg.role]"
    >
      <div class="avatar">
        {{ msg.role === 'user' ? 'U' : 'AI' }}
      </div>
      <div class="content">
        <pre>{{ msg.content }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import type { Message } from '../stores/trip'

const props = defineProps<{
  messages: Message[]
}>()

const listRef = ref<HTMLElement | null>(null)

watch(() => props.messages, () => {
  nextTick(() => {
    if (listRef.value) {
      listRef.value.scrollTop = listRef.value.scrollHeight
    }
  })
}, { deep: true })
</script>

<style scoped>
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.message {
  display: flex;
  gap: 12px;
}
.message.user {
  flex-direction: row-reverse;
}
.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: #409eff;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: bold;
  flex-shrink: 0;
}
.message.assistant .avatar {
  background: #67c23a;
}
.content {
  max-width: 80%;
  padding: 12px 16px;
  border-radius: 8px;
  background: #f4f4f5;
  font-size: 14px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
.content pre {
  margin: 0;
  white-space: pre-wrap;
  font-family: inherit;
}
.message.user .content {
  background: #ecf5ff;
}
</style>
