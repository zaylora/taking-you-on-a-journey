import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ClarifyPayload, DayPlan, Budget } from '../types'

export interface Message {
  role: 'user' | 'assistant'
  content: string
  kind?: 'text' | 'clarify' | 'error'   // clarify 问题气泡区别于普通文本，error 错误消息
}

export const useTripStore = defineStore('trip', () => {
  const messages = ref<Message[]>([])
  const agentProgress = ref<Record<string, 'running' | 'done'>>({})
  const nodeLabels = ref<Record<string, string>>({})   // node_start 携带的后端友好文案
  const threadId = ref<string | null>(null)
  const dayPlans = ref<DayPlan[]>([])
  const activeDay = ref<number | null>(null)
  const activePoiId = ref<string | null>(null)
  const clarifyPending = ref<ClarifyPayload | null>(null)
  const budget = ref<Budget | null>(null)

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
  const setDayPlans = (plans: DayPlan[]) => {
    dayPlans.value = plans
    if (plans.length > 0) {
      activeDay.value = plans[0].day
      activePoiId.value = null
    } else {
      activeDay.value = null
      activePoiId.value = null
    }
  }
  const setActiveDay = (d: number | null) => { activeDay.value = d }
  const setActivePoi = (id: string | null) => { activePoiId.value = id }
  const setBudget = (b: Budget | null) => { budget.value = b }

  return {
    messages, agentProgress, nodeLabels, threadId, dayPlans, clarifyPending,
    activeDay, activePoiId, budget,
    addMessage, appendToLastMessage, startNode, endNode, clearProgress,
    setThreadId, setClarify, clearClarify, setDayPlans, setActiveDay, setActivePoi, setBudget,
  }
})
