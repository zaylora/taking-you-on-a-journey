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
