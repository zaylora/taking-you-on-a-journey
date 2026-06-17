import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface Message {
  role: 'user' | 'assistant'
  content: string
}

export const useTripStore = defineStore('trip', () => {
  const messages = ref<Message[]>([])
  const agentProgress = ref<string[]>([])
  
  const addMessage = (role: 'user' | 'assistant', content: string) => {
    messages.value.push({ role, content })
  }
  
  const appendToLastMessage = (text: string) => {
    if (messages.value.length === 0 || messages.value[messages.value.length - 1].role !== 'assistant') {
      addMessage('assistant', text)
    } else {
      messages.value[messages.value.length - 1].content += text
    }
  }

  const startNode = (node: string) => {
    if (!agentProgress.value.includes(node)) {
      agentProgress.value.push(node)
    }
  }

  const endNode = (_node: string) => {
    // 如果我们想移除节点或将其保留为已完成状态，目前我们先保留它并可能显示为已完成状态
    // M1 规范提到 "node_start/end 点亮"，因此我们可能只需要追踪活动节点即可。
    // 让我们暂时只更新活动节点，或已完成节点数组。
  }

  const clearProgress = () => {
    agentProgress.value = []
  }

  return {
    messages,
    agentProgress,
    addMessage,
    appendToLastMessage,
    startNode,
    endNode,
    clearProgress
  }
})
