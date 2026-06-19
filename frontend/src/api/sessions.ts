import type { SessionListItem, SessionSnapshot } from '../types'

const baseUrl = () => import.meta.env.VITE_API_BASE || 'http://localhost:8000'

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl()}${path}`, init)
  if (!response.ok) {
    throw new Error(`HTTP 错误! 状态码: ${response.status}`)
  }
  return response.json() as Promise<T>
}

export async function createSession() {
  return requestJson<SessionListItem>('/api/sessions', { method: 'POST' })
}

export async function listSessions() {
  return requestJson<{ sessions: SessionListItem[] }>('/api/sessions')
}

export async function getSession(threadId: string) {
  return requestJson<SessionSnapshot>(`/api/sessions/${threadId}`)
}

export async function deleteSession(threadId: string) {
  const response = await fetch(`${baseUrl()}/api/sessions/${threadId}`, { method: 'DELETE' })
  if (!response.ok) {
    throw new Error(`HTTP 错误! 状态码: ${response.status}`)
  }
}
