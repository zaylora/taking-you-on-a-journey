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
      <div class="content" :class="{ 'clarify-bubble': msg.kind === 'clarify' }">
        <div class="markdown-body" v-html="renderMarkdown(msg.content)"></div>
      </div>
    </div>
    
    <div v-if="hasProgress && loading" class="message assistant">
      <div class="avatar">AI</div>
      <div class="content progress-bubble">
        <AgentProgress />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'
import MarkdownIt from 'markdown-it'
import type { Message } from '../stores/trip'
import { useTripStore } from '../stores/trip'
import AgentProgress from './AgentProgress.vue'

const props = defineProps<{
  messages: Message[],
  loading: boolean
}>()

const md = new MarkdownIt({ breaks: true, linkify: true })

const renderMarkdown = (text: string | undefined) => {
  return md.render(text || '')
}

const tripStore = useTripStore()
const hasProgress = computed(() => Object.keys(tripStore.agentProgress).length > 0)

const listRef = ref<HTMLElement | null>(null)

watch([() => props.messages, hasProgress, () => props.loading], () => {
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
  word-break: break-word;
}
.message.user .content {
  background: #ecf5ff;
}
.content.clarify-bubble { background: #fdf6ec; border: 1px solid #f5dab1; color: #b88230; }
.progress-bubble { background: transparent; padding: 0; }

/* Markdown Styles */
:deep(.markdown-body p) {
  margin: 0 0 8px 0;
}
:deep(.markdown-body p:last-child) {
  margin-bottom: 0;
}
:deep(.markdown-body pre) {
  background-color: #282c34;
  color: #abb2bf;
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 8px 0;
}
:deep(.markdown-body code) {
  background-color: rgba(0, 0, 0, 0.05);
  padding: 2px 4px;
  border-radius: 4px;
  font-family: monospace;
}
:deep(.markdown-body pre code) {
  background-color: transparent;
  padding: 0;
  color: inherit;
}
:deep(.markdown-body ul), :deep(.markdown-body ol) {
  margin: 8px 0;
  padding-left: 20px;
}
:deep(.markdown-body li) {
  margin-bottom: 4px;
}
:deep(.markdown-body blockquote) {
  border-left: 4px solid #dcdfe6;
  margin: 8px 0;
  padding-left: 12px;
  color: #606266;
}
:deep(.markdown-body table) {
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0;
}
:deep(.markdown-body th), :deep(.markdown-body td) {
  border: 1px solid #dcdfe6;
  padding: 6px 12px;
}
:deep(.markdown-body h1), :deep(.markdown-body h2), :deep(.markdown-body h3), 
:deep(.markdown-body h4), :deep(.markdown-body h5), :deep(.markdown-body h6) {
  margin: 12px 0 8px 0;
  font-weight: 600;
}
:deep(.markdown-body h1:first-child), :deep(.markdown-body h2:first-child), 
:deep(.markdown-body h3:first-child), :deep(.markdown-body h4:first-child), 
:deep(.markdown-body h5:first-child), :deep(.markdown-body h6:first-child) {
  margin-top: 0;
}
</style>