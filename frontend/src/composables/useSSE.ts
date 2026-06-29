import { ref } from 'vue'
import { fetchChatStream } from '../api/sse'
import { useTripStore } from '../stores/trip'
import { ElMessage } from 'element-plus'
import type {
  EventName, NodeStartPayload, TokenPayload, NodeEndPayload,
  ErrorPayload, SessionPayload, FinalPayload,
  TitlePayload, PlanPatchPayload, ToolCallPayload, ToolResultPayload,
  ClarifyPayload,
} from '../types'

export function useSSE() {
  const loading = ref(false)
  const tripStore = useTripStore()
  let abortController: AbortController | null = null

  const send = async (message: string) => {
    if (!message.trim()) return
    loading.value = true

    try {
      const activeThreadId = await tripStore.ensureConversation()
      tripStore.addMessage('user', message)
      tripStore.setPendingClarify(null)
      tripStore.clearProgress()
      abortController = new AbortController()

      await fetchChatStream(message, activeThreadId, (eventStr, data) => {
        switch (eventStr as EventName) {
          case 'session':
            tripStore.setThreadId((data as SessionPayload).thread_id)
            break
          case 'title': {
            const p = data as TitlePayload
            tripStore.setTitle(p.thread_id, p.title)
            break
          }
          case 'plan_patch': {
            const p = data as PlanPatchPayload
            tripStore.setPlanVersion(p.plan_version)
            break
          }
          case 'node_start': {
            const p = data as NodeStartPayload
            tripStore.startNode(p.node, p.label)
            break
          }
          case 'node_end':
            tripStore.endNode((data as NodeEndPayload).node)
            break
          case 'tool_call': {
            const p = data as ToolCallPayload
            tripStore.startToolCall(p.tool, p.label)
            break
          }
          case 'tool_result':
            tripStore.endToolCall((data as ToolResultPayload).tool)
            break
          case 'token':
            tripStore.appendToken((data as TokenPayload).text)
            break
          case 'clarify':
            tripStore.addClarifyMessage(data as ClarifyPayload)
            tripStore.setPendingClarify(data as ClarifyPayload)
            tripStore.touchActive()
            loading.value = false
            break
          case 'final':
            tripStore.setDayPlans((data as FinalPayload).day_plans || [])
            tripStore.setBudget((data as FinalPayload).budget ?? null)
            if ((data as FinalPayload).plan_version !== undefined) {
              tripStore.setPlanVersion((data as FinalPayload).plan_version || 0)
            }
            tripStore.touchActive()
            loading.value = false
            break
          case 'error':
            {
              const message = (data as ErrorPayload).message || '生成失败'
              tripStore.addMessage('assistant', message, 'error')
              ElMessage.error(message)
            }
            loading.value = false
            break
          default:
            console.warn('未知事件:', eventStr)
        }
      }, abortController.signal)
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        console.error('SSE 连接错误:', e)
        ElMessage.error('连接错误')
      }
    } finally {
      loading.value = false
    }
  }

  const abort = () => {
    if (abortController) { abortController.abort(); abortController = null; loading.value = false }
  }

  return { loading, send, abort }
}
