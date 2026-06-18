export interface NodeStartPayload { node: string; label?: string }
export interface TokenPayload { text: string }
export interface NodeEndPayload { node: string }
export interface FinalPayload { answer: string; day_plans?: DayPlan[] }
export interface ErrorPayload { message: string }
export interface SessionPayload { thread_id: string }
export interface ClarifyPayload { field: string; question: string; options: string[] }

export interface LngLat { lng: number; lat: number }
export interface DayWeather { text: string; temp: string; is_rainy: boolean; source: string }
export interface TripItem {
  type: 'attraction' | 'meal'
  name: string
  poi_id: string
  location: LngLat
  indoor?: boolean        // 仅 attraction 有
}
export interface DayPlan {
  day: number
  items: TripItem[]
  center: LngLat
  weather: DayWeather
}

export type EventName =
  | 'session' | 'node_start' | 'token' | 'node_end' | 'clarify' | 'final' | 'error';
