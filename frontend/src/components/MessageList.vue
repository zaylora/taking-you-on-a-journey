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
        <template v-for="(seg, sIdx) in displaySegments(msg)" :key="sIdx">
          <!-- 工具 pill -->
          <div v-if="seg.kind === 'tool'" class="node-pill" :class="{ done: seg.status === 'done' }">
            <span v-if="seg.status === 'running'" class="loading-icon"></span>
            <span v-else class="done-icon">✓</span>
            <span class="node-label">{{ seg.label }}</span>
          </div>
          <!-- 最终回复：黑色常展开 -->
          <div v-else-if="seg.role === 'answer'" class="markdown-body" v-html="renderMarkdown(seg.text)"></div>
          <!-- 中间推理：淡色，写完折叠 -->
          <div v-else class="reasoning-block">
            <div class="reasoning-head" @click="toggleReasoning(index, sIdx)">
              <span class="reasoning-caret">{{ isReasoningOpen(index, sIdx, seg) ? '▾' : '▸' }}</span>
              <span>{{ isReasoningOpen(index, sIdx, seg) ? '思考中…' : '已思考' }}</span>
            </div>
            <div v-if="isReasoningOpen(index, sIdx, seg)" class="reasoning-body markdown-body"
                 v-html="renderMarkdown(seg.text)"></div>
          </div>
        </template>
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

const props = defineProps<{
  messages: Message[],
  loading: boolean
}>()

const md = new MarkdownIt({ breaks: true, linkify: true })

const renderMarkdown = (text: unknown) => {
  return md.render(typeof text === 'string' ? text : String(text ?? ''))
}

const tripStore = useTripStore()

type DisplaySegment =
  | { kind: 'tool'; tool: string; label: string; status: 'running' | 'done' }
  | { kind: 'text'; text: string; role: 'reasoning' | 'answer' }

// 渲染期判定：最后一个 text 段为 answer，其余为 reasoning
const displaySegments = (msg: Message): DisplaySegment[] => {
  const segs = msg.segments ?? []
  let lastTextIdx = -1
  segs.forEach((s, i) => { if (s.kind === 'text') lastTextIdx = i })
  return segs.map((s, i) => {
    if (s.kind === 'tool') return s
    return { kind: 'text', text: s.text, role: i === lastTextIdx ? 'answer' : 'reasoning' }
  })
}

// 用户手动展开的 reasoning 段：键为 `${msgIdx}:${segIdx}`
const manuallyOpen = ref<Set<string>>(new Set())
const reasoningKey = (m: number, s: number) => `${m}:${s}`
const toggleReasoning = (m: number, s: number) => {
  const k = reasoningKey(m, s)
  const next = new Set(manuallyOpen.value)
  next.has(k) ? next.delete(k) : next.add(k)
  manuallyOpen.value = next
}
// 展开条件：用户手动展开，或它是最后一条消息里正在写入的最后一段（流式中）
const isReasoningOpen = (m: number, s: number, _seg: DisplaySegment): boolean => {
  if (manuallyOpen.value.has(reasoningKey(m, s))) return true
  if (!props.loading) return false
  if (m !== props.messages.length - 1) return false
  const segs = props.messages[m].segments ?? []
  return s === segs.length - 1 && segs[s]?.kind === 'text'
}

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
  const segs = msg.segments ?? []
  const last = segs[segs.length - 1]
  if (last && last.kind === 'text' && last.text) return false  // 正在出正文
  if (segs.some((s) => s.kind === 'tool' && s.status === 'running')) return false
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

/* Tool pill 样式（从 AgentProgress 迁移） */
.node-pill {
  display: inline-flex; align-items: center; padding: 6px 14px; margin: 4px 0;
  background-color: var(--el-fill-color-light, #f4f4f5);
  border: 1px solid var(--el-border-color-lighter, #e4e7ed);
  border-radius: 20px; font-size: 13px; color: var(--el-text-color-regular, #606266);
}
.node-pill.done { opacity: 0.7; background-color: var(--el-color-success-light-9, #f0f9eb);
  border-color: var(--el-color-success-light-7, #e1f3d8); }
.node-pill .node-label { line-height: 1; font-weight: 500; }
.node-pill .loading-icon { width: 12px; height: 12px; margin-right: 8px;
  border: 2px solid var(--el-color-primary, #409eff); border-top-color: transparent;
  border-radius: 50%; animation: spin 0.8s linear infinite; }
.node-pill .done-icon { width: 12px; height: 12px; margin-right: 8px;
  color: var(--el-color-success, #67c23a); font-weight: bold; line-height: 12px; text-align: center; }

/* Reasoning 折叠块样式 */
.reasoning-block { margin: 6px 0; }
.reasoning-head { display: inline-flex; align-items: center; gap: 6px; cursor: pointer;
  color: var(--el-text-color-secondary, #909399); font-size: 13px; user-select: none; }
.reasoning-caret { font-size: 11px; }
.reasoning-body { color: var(--el-text-color-secondary, #909399); font-size: 13px;
  margin-top: 4px; padding-left: 14px; border-left: 2px solid var(--el-border-color-lighter, #e4e7ed); }

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
