import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ClarifyPayload } from '../types'

export interface Message {
  role: 'user' | 'assistant'
  content: string
  kind?: 'text' | 'clarify'   // clarify 问题气泡区别于普通文本
}

export const useTripStore = defineStore('trip', () => {
  const messages = ref<Message[]>([])
  const agentProgress = ref<Record<string, 'running' | 'done'>>({})
  const nodeLabels = ref<Record<string, string>>({})   // node_start 携带的后端友好文案
  const threadId = ref<string | null>(null)
  const dayPlans = ref<any[]>([])
  const clarifyPending = ref<ClarifyPayload | null>(null)

  const addMessage = (role: 'user' | 'assistant', content: string, kind: 'text' | 'clarify' | 'error' = 'text') => {
    messages.value.push({ role, content, kind })
  }
  const appendToLastMessage = (text: string) => {
    const last = messages.value[messages.value.length - 1]
    if (!last || last.role !== 'assistant' || last.kind === 'clarify') {
      addMessage('assistant', text)
    } else {
      last.content += text
    }
  }
  const startNode = (node: string, label?: string) => {
    agentProgress.value[node] = 'running'
    if (label) nodeLabels.value[node] = label
  }
  const endNode = (node: string) => { agentProgress.value[node] = 'done' }
  const clearProgress = () => { agentProgress.value = {}; nodeLabels.value = {} }

  const setThreadId = (id: string) => { threadId.value = id }
  const setClarify = (c: ClarifyPayload) => {
    clarifyPending.value = c
    addMessage('assistant', c.question, 'clarify')
  }
  const clearClarify = () => { clarifyPending.value = null }
  const setDayPlans = (plans: any[]) => { dayPlans.value = plans }

  return {
    messages, agentProgress, nodeLabels, threadId, dayPlans, clarifyPending,
    addMessage, appendToLastMessage, startNode, endNode, clearProgress,
    setThreadId, setClarify, clearClarify, setDayPlans,
  }
})
