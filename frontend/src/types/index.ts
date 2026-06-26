export interface NodeStartPayload { node: string; label?: string }
export interface TokenPayload { text: string }
export interface NodeEndPayload { node: string }
export interface ToolCallPayload { tool: string; label: string }
export interface ToolResultPayload { tool: string; label: string }
export interface BudgetBreakdown { ticket: number; hotel: number; food: number; transport: number }
export interface Budget {
  limit: number
  estimated: number
  over: boolean
  breakdown: BudgetBreakdown
  retry_count: number
  note: string
}
export interface FinalPayload { answer: string; day_plans?: DayPlan[]; budget?: Budget; plan_version?: number }
export interface ErrorPayload { message: string }
export interface SessionPayload { thread_id: string }
export interface TitlePayload { thread_id: string; title: string }
export interface PlanPatchPayload { plan_version: number; changed_days: number[] }
export interface ClarifyPayload { field: string; question: string; options: string[] }

export interface SessionListItem {
  thread_id: string
  title: string
  created_at: string
  updated_at: string
}

export interface SessionSnapshot extends SessionListItem {
  messages: Array<{
    role: 'user' | 'assistant'
    content: string
    kind?: 'text' | 'clarify' | 'error'
    tool_steps?: Array<{ tool: string; label: string; status: 'done' }>
  }>
  day_plans: DayPlan[]
  budget: Budget | Record<string, never>
  plan_version: number
}

export interface LngLat { lng: number; lat: number }
export interface DayWeather { text: string; temp: string; is_rainy: boolean; source: string }
export interface TripItem {
  type: 'attraction' | 'meal' | 'transport'
  name: string
  poi_id: string
  location: LngLat
  indoor?: boolean
  cost?: number
  start?: string
  end?: string
  note?: string
  mode?: string
  from?: string
  to?: string
  routeInfo?: { distance: number; time: number }
}
export interface Hotel {
  name: string
  poi_id: string
  location: LngLat
  price: number
  level: string
}
export interface DayPlan {
  day: number
  items: TripItem[]
  center: LngLat
  weather: DayWeather
  hotel?: Hotel | null    // 当晚住宿；离程日为 null，M4
}

export type EventName =
  | 'session' | 'title' | 'plan_patch' | 'intent'
  | 'node_start' | 'token' | 'node_end' | 'clarify' | 'final' | 'error'
  | 'tool_call' | 'tool_result';
