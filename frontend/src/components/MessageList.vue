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
        <AgentProgress
          v-if="msg.role === 'assistant' && msg.toolSteps?.length"
          :tool-steps="msg.toolSteps"
        />
        <div
          v-if="msg.content"
          class="markdown-body"
          v-html="renderMarkdown(msg.content)"
        ></div>
      </div>
    </div>

    <!-- 瞬态阶段提示：展示后端 node_start 发来的阶段 label（如"正在思考..."），
         仅 loading 期间、最后一条尚无工具链/正文时出现，不写入消息数组，
         避免破坏实时与历史一致；工具链出现后由 pill 表达进度 -->
    <div v-if="showThinking" class="message assistant">
      <div class="avatar">AI</div>
      <div class="content thinking-bubble">
        <span class="loading-icon"></span>
        <span>{{ thinkingLabel }}</span>
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

const renderMarkdown = (text: unknown) => {
  return md.render(typeof text === 'string' ? text : String(text ?? ''))
}

const tripStore = useTripStore()

// loading 中且最后一条消息还没有任何可显示进度（工具链或正文）时，
// 给出阶段提示。一旦工具链或正文出现即隐藏。
const showThinking = computed(() => {
  if (!props.loading) return false
  const last = props.messages[props.messages.length - 1]
  if (last && last.role === 'assistant' && (last.toolSteps?.length || last.content)) return false
  return true
})

// 取当前正在 running 的 node 的后端 label，无则回退"正在思考…"
const thinkingLabel = computed(() => {
  const progress = tripStore.agentProgress
  const labels = tripStore.nodeLabels
  for (const node of Object.keys(progress)) {
    if (progress[node] === 'running' && labels[node]) return labels[node]
  }
  return '正在思考…'
})

const listRef = ref<HTMLElement | null>(null)

watch([() => props.messages, showThinking, () => props.loading], () => {
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

/* 瞬态思考气泡 */
.thinking-bubble {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--el-text-color-regular, #606266);
}
.thinking-bubble .loading-icon {
  width: 12px;
  height: 12px;
  border: 2px solid var(--el-color-primary, #409eff);
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

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