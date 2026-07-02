import type {
  Budget,
  ChatMessage,
  ChatPart,
  SessionListItem,
  SessionMessage,
  SessionSegment,
  SessionSnapshot,
  TripUiState,
} from "./types";

const defaultBaseUrl = () =>
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${defaultBaseUrl()}${path}`;
  const response = init ? await fetch(url, init) : await fetch(url);
  if (!response.ok) {
    throw new Error(`HTTP error ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function createSession() {
  return requestJson<SessionListItem>("/api/sessions", { method: "POST" });
}

export function listSessions() {
  return requestJson<{ sessions: SessionListItem[] }>("/api/sessions");
}

export function getSession(threadId: string) {
  return requestJson<SessionSnapshot>(`/api/sessions/${threadId}`);
}

export function tripStateFromSessionSnapshot(
  snapshot: SessionSnapshot,
): Partial<TripUiState> {
  const dayPlans = snapshot.day_plans ?? [];

  return {
    threadId: snapshot.thread_id,
    messages: normalizeMessages(snapshot.messages ?? []),
    dayPlans,
    budget: normalizeBudget(snapshot.budget),
    planVersion: snapshot.plan_version ?? 0,
    artifactOpen: dayPlans.length > 0,
    activeDay: dayPlans[0]?.day ?? null,
    activePoiId: null,
    nodeProgress: {},
    nodeLabels: {},
    activeNodeLabel: null,
    loading: false,
    error: null,
  };
}

function normalizeMessages(messages: SessionMessage[]): ChatMessage[] {
  let userCount = 0;
  let assistantCount = 0;

  return messages
    .filter((message) => message.role === "user" || message.role === "assistant")
    .map((message) => {
      const id =
        message.role === "user"
          ? `user-${++userCount}`
          : `assistant-${++assistantCount}`;
      const kind: ChatMessage["kind"] =
        message.kind === "error" ? "error" : "text";

      return {
        id,
        role: message.role,
        parts: normalizeParts(message),
        kind,
      };
    })
    .filter((message) => message.parts.length > 0 || message.kind === "error");
}

function normalizeParts(message: SessionMessage): ChatPart[] {
  const parts = (message.segments ?? []).flatMap(segmentToPart);
  if (parts.length > 0) return parts;

  const content = stringValue(message.content);
  return content ? [{ type: "text", text: content }] : [];
}

function segmentToPart(segment: SessionSegment): ChatPart[] {
  if (segment.kind === "tool") {
    return [
      {
        type: "tool",
        tool: stringValue(segment.tool) ?? "tool",
        label: stringValue(segment.label) ?? "已完成",
        status: segment.status === "running" ? "running" : "done",
      },
    ];
  }

  const text = stringValue(segment.text);
  return text ? [{ type: "text", text }] : [];
}

function normalizeBudget(value: SessionSnapshot["budget"]): Budget | null {
  if (!isObject(value) || Object.keys(value).length === 0) return null;
  return value as Budget;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
