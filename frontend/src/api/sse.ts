export async function fetchChatStream(
  message: string,
  threadId: string | null,
  onChunk: (event: string, data: any) => void,
  signal?: AbortSignal
) {
  const baseUrl = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
  const response = await fetch(`${baseUrl}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, thread_id: threadId }),
    signal
  })

  if (!response.ok) {
    throw new Error(`HTTP 错误! 状态码: ${response.status}`)
  }

  const reader = response.body?.getReader()
  if (!reader) throw new Error('未找到可读流')

  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    
    // 最后一部分可能是不完整的，保留在缓冲区中
    buffer = parts.pop() || ''

    for (const part of parts) {
      if (part.trim() === '') continue
      const lines = part.split('\n')
      let event = 'message'
      let dataStr = ''

      for (const line of lines) {
        if (line.startsWith(':')) continue // 忽略 SSE 注释/心跳行
        if (line.startsWith('event: ')) {
          event = line.slice(7).trim()
        } else if (line.startsWith('data: ')) {
          dataStr = line.slice(6)
        }
      }

      if (dataStr) {
        try {
          const data = JSON.parse(dataStr)
          onChunk(event, data)
        } catch (e) {
          console.error('解析 SSE 数据失败:', dataStr, e)
        }
      }
    }
  }
}
