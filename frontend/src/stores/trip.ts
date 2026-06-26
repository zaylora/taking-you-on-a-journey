import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { createSession, getSession, listSessions } from '../api/sessions'
import type { DayPlan, Budget, TripItem, SessionSnapshot } from '../types'

export interface ToolStep {
  tool: string
  label: string
  status: 'running' | 'done'
}

export interface Message {
  role: 'user' | 'assistant'
  content: string
  kind?: 'text' | 'error'
  toolSteps?: ToolStep[]
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
      messages: (snapshot.messages || [])
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .map((m) => ({
          role: m.role,
          content: m.content,
          kind: m.kind,
          toolSteps: m.tool_steps?.map((s) => ({ ...s, status: 'done' as const })) || undefined,
        })),
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
  }

  const setActiveThread = (id: string | null) => {
    activeThreadId.value = id
    if (id) localStorage.setItem(STORAGE_KEY, id)
    else localStorage.removeItem(STORAGE_KEY)
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

  const addMessage = (role: 'user' | 'assistant', content: string, kind: 'text' | 'error' = 'text') => {
    activeConversation.value?.messages.push({ role, content, kind })
  }

  const appendToLastMessage = (text: string) => {
    const msg = ensureAssistantMessage()
    if (msg) msg.content += text
  }

  const startNode = (node: string, label?: string) => {
    agentProgress.value[node] = 'running'
    if (label) nodeLabels.value[node] = label
  }
  const endNode = (node: string) => { agentProgress.value[node] = 'done' }

  // 取得当前可追加的 assistant 占位消息：最后一条是 assistant 则复用，
  // 否则新建一条空 assistant 消息。保证实时流的工具链/正文始终挂在同一条消息上，
  // 与历史快照「单条消息内聚合」的形态一致。
  const ensureAssistantMessage = (): Message | null => {
    const current = activeConversation.value
    if (!current) return null
    const last = current.messages[current.messages.length - 1]
    if (last && last.role === 'assistant') return last
    const msg: Message = { role: 'assistant', content: '', kind: 'text' }
    current.messages.push(msg)
    return msg
  }

  // 工具开始：把上一个仍在 running 的步骤收尾（ReAct 串行执行），再追加新步骤到 assistant 消息
  const startToolCall = (tool: string, label: string) => {
    const msg = ensureAssistantMessage()
    if (!msg) return
    if (!msg.toolSteps) msg.toolSteps = []
    for (const s of msg.toolSteps) if (s.status === 'running') s.status = 'done'
    msg.toolSteps.push({ tool, label, status: 'running' })
  }
  // 工具结束：把最近一个同名 running 步骤标记 done
  const endToolCall = (tool: string) => {
    const current = activeConversation.value
    if (!current) return
    const last = current.messages[current.messages.length - 1]
    if (last && last.role === 'assistant' && last.toolSteps) {
      for (let i = last.toolSteps.length - 1; i >= 0; i--) {
        if (last.toolSteps[i].tool === tool && last.toolSteps[i].status === 'running') {
          last.toolSteps[i].status = 'done'
          break
        }
      }
    }
  }

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
    messages, agentProgress, nodeLabels, threadId, dayPlans,
    toolSteps,
    activeDay, activePoiId, activeTransport, budget,
    loadConversations, loadConversation, createConversation, ensureConversation,
    addMessage, appendToLastMessage, startNode, endNode, clearProgress,
    startToolCall, endToolCall,
    setThreadId, setTitle, setDayPlans, setActiveDay,
    setActivePoi, setActiveTransport, setBudget, setPlanVersion, touchActive,
  }
})
