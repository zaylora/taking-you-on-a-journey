import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { createSession, getSession, listSessions } from '../api/sessions'
import type { ClarifyPayload, DayPlan, Budget, TripItem, SessionSnapshot } from '../types'

export interface Message {
  role: 'user' | 'assistant'
  content: string
  kind?: 'text' | 'clarify' | 'error'
}

export interface Conversation {
  threadId: string
  title: string
  messages: Message[]
  dayPlans: DayPlan[]
  budget: Budget | null
  activeDay: number | null
  activePoiId: string | null
  activeTransport: TripItem | null
  planVersion: number
  updatedAt: string
}

const STORAGE_KEY = 'trip.activeThreadId'

const emptyConversation = (
  threadId: string,
  title = '新的行程',
  updatedAt = new Date().toISOString(),
): Conversation => ({
  threadId,
  title,
  messages: [],
  dayPlans: [],
  budget: null,
  activeDay: null,
  activePoiId: null,
  activeTransport: null,
  planVersion: 0,
  updatedAt,
})

const budgetFromSnapshot = (snapshot: SessionSnapshot): Budget | null => {
  if (!snapshot.budget || !('estimated' in snapshot.budget)) return null
  return snapshot.budget as Budget
}

export const useTripStore = defineStore('trip', () => {
  const conversations = ref<Conversation[]>([])
  const activeThreadId = ref<string | null>(localStorage.getItem(STORAGE_KEY))
  const agentProgress = ref<Record<string, 'running' | 'done'>>({})
  const nodeLabels = ref<Record<string, string>>({})
  // 工具调用过程链：按发生顺序记录每次工具调用及其状态（running→done）
  const toolSteps = ref<Array<{ tool: string; label: string; status: 'running' | 'done' }>>([])
  // 推理模型思考过程（reasoning_content）增量累积；非推理模型则恒为空
  const thinkingText = ref('')
  const clarifyPending = ref<ClarifyPayload | null>(null)

  const activeConversation = computed(() =>
    conversations.value.find((c) => c.threadId === activeThreadId.value) ?? null,
  )

  const messages = computed(() => activeConversation.value?.messages ?? [])
  const threadId = computed(() => activeConversation.value?.threadId ?? activeThreadId.value)
  const dayPlans = computed(() => activeConversation.value?.dayPlans ?? [])
  const budget = computed(() => activeConversation.value?.budget ?? null)
  const activeDay = computed(() => activeConversation.value?.activeDay ?? null)
  const activePoiId = computed(() => activeConversation.value?.activePoiId ?? null)
  const activeTransport = computed(() => activeConversation.value?.activeTransport ?? null)

  const upsertConversation = (conversation: Conversation) => {
    const idx = conversations.value.findIndex((c) => c.threadId === conversation.threadId)
    if (idx >= 0) conversations.value[idx] = conversation
    else conversations.value.unshift(conversation)
    conversations.value.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
  }

  const applySnapshot = (snapshot: SessionSnapshot) => {
    upsertConversation({
      threadId: snapshot.thread_id,
      title: snapshot.title,
      messages: snapshot.messages || [],
      dayPlans: snapshot.day_plans || [],
      budget: budgetFromSnapshot(snapshot),
      activeDay: snapshot.day_plans?.[0]?.day ?? null,
      activePoiId: null,
      activeTransport: null,
      planVersion: snapshot.plan_version || 0,
      updatedAt: snapshot.updated_at,
    })
  }

  const clearProgress = () => {
    agentProgress.value = {}
    nodeLabels.value = {}
    toolSteps.value = []
    thinkingText.value = ''
  }

  const setActiveThread = (id: string | null) => {
    activeThreadId.value = id
    if (id) localStorage.setItem(STORAGE_KEY, id)
    else localStorage.removeItem(STORAGE_KEY)
    clarifyPending.value = null
    clearProgress()
  }

  const createConversation = async () => {
    const session = await createSession()
    upsertConversation(emptyConversation(session.thread_id, session.title, session.updated_at))
    setActiveThread(session.thread_id)
    return session.thread_id
  }

  const ensureConversation = async () => {
    if (activeConversation.value) return activeConversation.value.threadId
    return createConversation()
  }

  const loadConversation = async (id: string) => {
    const snapshot = await getSession(id)
    applySnapshot(snapshot)
    setActiveThread(id)
  }

  const loadConversations = async () => {
    const { sessions } = await listSessions()
    conversations.value = sessions.map((s) => emptyConversation(s.thread_id, s.title, s.updated_at))
    const preferred = activeThreadId.value && conversations.value.some((c) => c.threadId === activeThreadId.value)
      ? activeThreadId.value
      : conversations.value[0]?.threadId ?? null
    setActiveThread(preferred)
    if (preferred) await loadConversation(preferred)
  }

  const addMessage = (role: 'user' | 'assistant', content: string, kind: 'text' | 'clarify' | 'error' = 'text') => {
    activeConversation.value?.messages.push({ role, content, kind })
  }

  const appendToLastMessage = (text: string) => {
    const current = activeConversation.value
    if (!current) return
    const last = current.messages[current.messages.length - 1]
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

  // 工具开始：把上一个仍在 running 的步骤收尾（ReAct 串行执行），再追加新步骤
  const startToolCall = (tool: string, label: string) => {
    for (const s of toolSteps.value) if (s.status === 'running') s.status = 'done'
    toolSteps.value.push({ tool, label, status: 'running' })
  }
  // 工具结束：把最近一个同名 running 步骤标记 done
  const endToolCall = (tool: string) => {
    for (let i = toolSteps.value.length - 1; i >= 0; i--) {
      if (toolSteps.value[i].tool === tool && toolSteps.value[i].status === 'running') {
        toolSteps.value[i].status = 'done'
        break
      }
    }
  }
  const appendThinking = (text: string) => { thinkingText.value += text }

  const setThreadId = (id: string) => {
    if (!conversations.value.some((c) => c.threadId === id)) {
      upsertConversation(emptyConversation(id))
    }
    setActiveThread(id)
  }

  const setTitle = (id: string, title: string) => {
    const conversation = conversations.value.find((c) => c.threadId === id)
    if (conversation) conversation.title = title
  }

  const setClarify = (c: ClarifyPayload) => {
    clarifyPending.value = c
    addMessage('assistant', c.question, 'clarify')
  }
  const clearClarify = () => { clarifyPending.value = null }

  const setDayPlans = (plans: DayPlan[]) => {
    const current = activeConversation.value
    if (!current) return
    current.dayPlans = plans
    if (plans.length > 0) {
      current.activeDay = null
      current.activePoiId = null
    } else {
      current.activeDay = null
      current.activePoiId = null
      current.activeTransport = null
      current.budget = null
    }
  }

  const setActiveDay = (d: number | null) => {
    const current = activeConversation.value
    if (!current) return
    current.activeDay = d
    current.activePoiId = null
    current.activeTransport = null
  }

  const setActivePoi = (id: string | null) => {
    const current = activeConversation.value
    if (!current) return
    current.activePoiId = id
    if (id) current.activeTransport = null
  }

  const setActiveTransport = (item: TripItem | null) => {
    const current = activeConversation.value
    if (!current) return
    current.activeTransport = item
    if (item) current.activePoiId = null
  }

  const setBudget = (b: Budget | null) => {
    if (activeConversation.value) activeConversation.value.budget = b
  }

  const setPlanVersion = (version: number) => {
    if (activeConversation.value) activeConversation.value.planVersion = version
  }

  const touchActive = () => {
    if (activeConversation.value) activeConversation.value.updatedAt = new Date().toISOString()
  }

  return {
    conversations, activeThreadId, activeConversation,
    messages, agentProgress, nodeLabels, threadId, dayPlans, clarifyPending,
    toolSteps, thinkingText,
    activeDay, activePoiId, activeTransport, budget,
    loadConversations, loadConversation, createConversation, ensureConversation,
    addMessage, appendToLastMessage, startNode, endNode, clearProgress,
    startToolCall, endToolCall, appendThinking,
    setThreadId, setTitle, setClarify, clearClarify, setDayPlans, setActiveDay,
    setActivePoi, setActiveTransport, setBudget, setPlanVersion, touchActive,
  }
})
