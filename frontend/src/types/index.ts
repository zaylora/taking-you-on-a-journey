export interface NodeStartPayload { node: string; label?: string }
export interface TokenPayload { text: string }
export interface NodeEndPayload { node: string }
export interface BudgetBreakdown { ticket: number; hotel: number; food: number; transport: number }
export interface Budget {
  limit: number
  estimated: number
  over: boolean
  breakdown: BudgetBreakdown
  retry_count: number
  note: string
}
export interface FinalPayload { answer: string; day_plans?: DayPlan[]; budget?: Budget }
export interface ErrorPayload { message: string }
export interface SessionPayload { thread_id: string }
export interface ClarifyPayload { field: string; question: string; options: string[] }

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
  | 'session' | 'node_start' | 'token' | 'node_end' | 'clarify' | 'final' | 'error';
