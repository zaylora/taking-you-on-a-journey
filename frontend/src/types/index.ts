export interface NodeStartPayload { node: string; label?: string }
export interface TokenPayload { text: string }
export interface NodeEndPayload { node: string }
export interface FinalPayload { answer: string; day_plans?: any[] }
export interface ErrorPayload { message: string }
export interface SessionPayload { thread_id: string }
export interface ClarifyPayload { field: string; question: string; options: string[] }

export type EventName =
  | 'session' | 'node_start' | 'token' | 'node_end' | 'clarify' | 'final' | 'error';
