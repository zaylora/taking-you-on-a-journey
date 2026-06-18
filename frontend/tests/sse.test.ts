import { afterEach, expect, test } from 'bun:test'
import { fetchChatStream } from '../src/api/sse'

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
})

test('parses CRLF-delimited SSE events', async () => {
  const body = [
    'event: session\r\n',
    'data: {"thread_id":"abc"}\r\n',
    '\r\n',
    'event: clarify\r\n',
    'data: {"field":"city","question":"你想去哪？","options":[]}\r\n',
    '\r\n',
  ].join('')
  const events: Array<{ event: string; data: any }> = []

  globalThis.fetch = async () => new Response(body, { status: 200 })

  await fetchChatStream('你好', null, (event, data) => {
    events.push({ event, data })
  })

  expect(events).toEqual([
    { event: 'session', data: { thread_id: 'abc' } },
    { event: 'clarify', data: { field: 'city', question: '你想去哪？', options: [] } },
  ])
})
