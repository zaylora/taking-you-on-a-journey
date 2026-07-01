import { afterEach, expect, mock, test } from 'bun:test'
import { createPinia, setActivePinia } from 'pinia'
import { fetchChatStream } from '../src/api/sse'
import { useTripStore } from '../src/stores/trip'

const originalFetch = globalThis.fetch
const originalLocalStorage = globalThis.localStorage

class MemoryStorage {
  private store = new Map<string, string>()

  getItem(key: string) {
    return this.store.get(key) ?? null
  }

  setItem(key: string, value: string) {
    this.store.set(key, value)
  }

  removeItem(key: string) {
    this.store.delete(key)
  }

  clear() {
    this.store.clear()
  }
}

afterEach(() => {
  globalThis.fetch = originalFetch
  mock.restore()
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: originalLocalStorage,
  })
})

test('parses CRLF-delimited SSE events', async () => {
  const body = [
    'event: session\r\n',
    'data: {"thread_id":"abc"}\r\n',
    '\r\n',
    'event: token\r\n',
    'data: {"text":"你想去哪？"}\r\n',
    '\r\n',
    'event: final\r\n',
    'data: {"answer":"你想去哪？"}\r\n',
    '\r\n',
  ].join('')
  const events: Array<{ event: string; data: any }> = []

  globalThis.fetch = async () => new Response(body, { status: 200 })

  await fetchChatStream('你好', null, (event, data) => {
    events.push({ event, data })
  })

  expect(events).toEqual([
    { event: 'session', data: { thread_id: 'abc' } },
    { event: 'token', data: { text: '你想去哪？' } },
    { event: 'final', data: { answer: '你想去哪？' } },
  ])
})

test('renders SSE error events into the active conversation', async () => {
  const toastError = mock(() => undefined)
  mock.module('element-plus', () => ({
    ElMessage: { error: toastError },
  }))

  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: new MemoryStorage(),
  })
  setActivePinia(createPinia())
  const store = useTripStore()
  store.setThreadId('thread-1')

  const body = [
    'event: session\n',
    'data: {"thread_id":"thread-1"}\n',
    '\n',
    'event: error\n',
    'data: {"message":"生成失败，请重试"}\n',
    '\n',
  ].join('')

  globalThis.fetch = async () => new Response(body, { status: 200 })

  const { useSSE } = await import('../src/composables/useSSE')
  const { send } = useSSE()
  await send('安排住宿')

  expect(store.messages).toEqual([
    {
      role: 'user',
      content: '安排住宿',
      kind: 'text',
      segments: [{ kind: 'text', text: '安排住宿' }],
    },
    {
      role: 'assistant',
      content: '生成失败，请重试',
      kind: 'error',
      segments: [{ kind: 'text', text: '生成失败，请重试' }],
    },
  ])
  expect(toastError).toHaveBeenCalledWith('生成失败，请重试')
})
