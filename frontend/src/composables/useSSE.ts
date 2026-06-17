import { ref } from 'vue'
import { fetchChatStream } from '../api/sse'
import { useTripStore } from '../stores/trip'
import { ElMessage } from 'element-plus'
import type { EventName, NodeStartPayload, TokenPayload, NodeEndPayload, ErrorPayload } from '../types'

export function useSSE() {
  const loading = ref(false)
  const tripStore = useTripStore()
  let abortController: AbortController | null = null

  const send = async (message: string) => {
    if (!message.trim()) return

    loading.value = true
    tripStore.addMessage('user', message)
    tripStore.clearProgress()
    
    abortController = new AbortController()

    try {
      await fetchChatStream(
        message,
        (eventStr, data) => {
          const event = eventStr as EventName
          switch (event) {
            case 'node_start':
              tripStore.startNode((data as NodeStartPayload).node)
              break
            case 'token':
              tripStore.appendToLastMessage((data as TokenPayload).text)
              break
            case 'node_end':
              tripStore.endNode((data as NodeEndPayload).node)
              break
            case 'final':
              // 后端发出的 final 意味着回答已完成。
              // 在 M1 中，我们逐字流式传输 token，因此 final 可能只是一个停止信号。
              loading.value = false
              break
            case 'error':
              ElMessage.error((data as ErrorPayload).message || '生成失败')
              loading.value = false
              break
            default:
              console.warn('未知事件:', event)
          }
        },
        abortController.signal
      )
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        console.error('SSE 连接错误:', e)
        ElMessage.error('连接错误')
        loading.value = false
      }
    } finally {
      loading.value = false
    }
  }

  const abort = () => {
    if (abortController) {
      abortController.abort()
      abortController = null
      loading.value = false
    }
  }

  return {
    loading,
    send,
    abort
  }
}
