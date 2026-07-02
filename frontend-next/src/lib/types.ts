export interface LngLat {
  lng: number;
  lat: number;
}

export interface DayWeather {
  text: string;
  temp?: string;
  is_rainy?: boolean;
  source?: string;
}

export interface TripItem {
  type: "attraction" | "meal" | "transport";
  name?: string;
  poi_id?: string;
  location?: LngLat;
  indoor?: boolean;
  cost?: number;
  start?: string;
  end?: string;
  note?: string;
  mode?: string;
  from?: string;
  to?: string;
  routeInfo?: { distance: number; time: number };
}

export interface Hotel {
  name: string;
  poi_id: string;
  location: LngLat;
  price?: number;
  level?: string;
}

export interface DayPlan {
  day: number;
  items: TripItem[];
  center?: LngLat;
  weather?: DayWeather;
  hotel?: Hotel | null;
}

export interface Budget {
  limit?: number;
  estimated?: number;
  over?: boolean;
  breakdown?: Partial<Record<"ticket" | "hotel" | "food" | "transport", number>>;
  retry_count?: number;
  note?: string;
}

export type ChatPart =
  | { type: "text"; text: string }
  | { type: "tool"; tool: string; label: string; status: "running" | "done" };

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  parts: ChatPart[];
  kind?: "text" | "error";
}

export type TripSseEventName =
  | "session"
  | "title"
  | "plan_patch"
  | "node_start"
  | "node_end"
  | "tool_call"
  | "tool_result"
  | "token"
  | "clarify"
  | "final"
  | "error";

export interface TripSseEvent {
  event: string;
  data: Record<string, unknown>;
}

export interface TripUiState {
  threadId: string | null;
  messages: ChatMessage[];
  dayPlans: DayPlan[];
  budget: Budget | null;
  planVersion: number;
  artifactOpen: boolean;
  activeDay: number | null;
  activePoiId: string | null;
  nodeProgress: Record<string, "running" | "done">;
  nodeLabels: Record<string, string>;
  activeNodeLabel: string | null;
  loading: boolean;
  error: string | null;
}
