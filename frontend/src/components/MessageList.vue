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
      <div class="content" :class="{ 'error-bubble': msg.kind === 'error' }">
        <AgentProgress
          v-if="msg.role === 'assistant' && msg.toolSteps?.length"
          :tool-steps="msg.toolSteps"
        />
        <div
          v-if="msg.content"
          class="markdown-body"
          v-html="renderMarkdown(msg.content)"
        ></div>
        <!-- 内联思考提示：工具链已收尾(全部 ✓)但正文尚未开始的间隙，
             或工具间的思考窗口，仍提示 Agent 在工作，避免界面"卡住" -->
        <div v-if="inlineThinking(msg, index)" class="thinking-bubble">
          <span class="loading-icon"></span>
          <span>{{ thinkingLabel }}</span>
        </div>
      </div>
    </div>

    <!-- 独立思考气泡：尚无 assistant 占位消息（最后一条仍是用户）时，
         给出阶段提示，不写入消息数组，避免破坏实时与历史一致 -->
    <div v-if="showStandaloneThinking" class="message assistant">
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

// 是否存在可复用的 assistant 占位消息（最后一条是 assistant）
const hasAssistantPlaceholder = computed(() => {
  const last = props.messages[props.messages.length - 1]
  return !!(last && last.role === 'assistant')
})

// 独立气泡：loading 中且还没有 assistant 占位消息时（首个工具/正文到达前）
const showStandaloneThinking = computed(() => {
  return props.loading && !hasAssistantPlaceholder.value
})

// 内联提示：仅对最后一条 assistant 消息生效。loading 中、正文尚未开始、
// 且没有正在 running 的工具（工具间或工具收尾后的思考窗口）时展示。
const inlineThinking = (msg: Message, index: number) => {
  if (!props.loading) return false
  if (index !== props.messages.length - 1) return false
  if (msg.role !== 'assistant') return false
  if (msg.content) return false
  if (msg.toolSteps?.some((s) => s.status === 'running')) return false
  return true
}

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

watch([() => props.messages, showStandaloneThinking, () => props.loading], () => {
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
.content.error-bubble { background: #fef0f0; border: 1px solid #fde2e2; color: #c45656; }

/* 瞬态思考气泡 */
.thinking-bubble {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--el-text-color-regular, #606266);
}
/* 内联在已有工具链/正文之后时，与上方内容留出间距 */
.content > .thinking-bubble:not(:first-child) {
  margin-top: 8px;
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
