import type {
  Budget,
  ChatMessage,
  ChatPart,
  DayPlan,
  TripSseEvent,
  TripUiState,
} from "./types";

export function createInitialTripState(
  patch: Partial<TripUiState> = {},
): TripUiState {
  return {
    threadId: null,
    messages: [],
    dayPlans: [],
    budget: null,
    planVersion: 0,
    artifactOpen: false,
    activeDay: null,
    activePoiId: null,
    nodeProgress: {},
    nodeLabels: {},
    activeNodeLabel: null,
    loading: false,
    error: null,
    ...patch,
  };
}

export function userMessage(text: string, index: number): ChatMessage {
  return {
    id: `user-${index}`,
    role: "user",
    parts: [{ type: "text", text }],
  };
}

export function applyTripEvent(state: TripUiState, event: TripSseEvent): TripUiState {
  const next: TripUiState = {
    ...state,
    messages: state.messages.map((message) => ({
      ...message,
      parts: message.parts.map((part) => ({ ...part }) as ChatPart),
    })),
    dayPlans: [...state.dayPlans],
  };

  switch (event.event) {
    case "session":
      next.threadId = stringValue(event.data.thread_id) ?? next.threadId;
      return next;
    case "node_start": {
      const node = stringValue(event.data.node);
      if (node) {
        next.nodeProgress = { ...next.nodeProgress, [node]: "running" };
        const label = stringValue(event.data.label);
        if (label) {
          next.nodeLabels = { ...next.nodeLabels, [node]: label };
          next.activeNodeLabel = label;
        } else {
          next.activeNodeLabel = next.nodeLabels[node] ?? "正在思考...";
        }
      }
      return next;
    }
    case "node_end": {
      const node = stringValue(event.data.node);
      if (node) {
        next.nodeProgress = { ...next.nodeProgress, [node]: "done" };
        next.activeNodeLabel = activeRunningNodeLabel(
          next.nodeProgress,
          next.nodeLabels,
        );
      }
      return next;
    }
    case "token":
      appendAssistantText(next, stringValue(event.data.text) ?? "");
      next.activeNodeLabel = null;
      return next;
    case "tool_call":
      appendTool(next, {
        tool: stringValue(event.data.tool) ?? "tool",
        label: stringValue(event.data.label) ?? "正在处理",
        status: "running",
      });
      next.activeNodeLabel = null;
      return next;
    case "tool_result":
      finishTool(
        next,
        stringValue(event.data.tool) ?? "",
        stringValue(event.data.label),
      );
      return next;
    case "final":
      if (Array.isArray(event.data.day_plans)) {
        next.dayPlans = event.data.day_plans as DayPlan[];
        next.artifactOpen = next.dayPlans.length > 0;
        next.activeDay = next.dayPlans[0]?.day ?? null;
      }
      if (isObject(event.data.budget)) {
        next.budget = event.data.budget as Budget;
      }
      if (typeof event.data.plan_version === "number") {
        next.planVersion = event.data.plan_version;
      }
      next.loading = false;
      next.activeNodeLabel = null;
      next.nodeProgress = markRunningNodesDone(next.nodeProgress);
      return next;
    case "error":
      next.error = stringValue(event.data.message) ?? "生成失败";
      next.loading = false;
      next.activeNodeLabel = null;
      next.nodeProgress = markRunningNodesDone(next.nodeProgress);
      appendAssistantText(next, next.error);
      return next;
    default:
      return next;
  }
}

export function setActiveDay(state: TripUiState, day: number | null): TripUiState {
  return { ...state, activeDay: day, activePoiId: null };
}

export function setActivePoi(state: TripUiState, poiId: string | null): TripUiState {
  return { ...state, activePoiId: poiId };
}

function ensureAssistantMessage(state: TripUiState): ChatMessage {
  const last = state.messages[state.messages.length - 1];
  if (last?.role === "assistant") return last;

  const message: ChatMessage = {
    id: `assistant-${state.messages.filter((item) => item.role === "assistant").length + 1}`,
    role: "assistant",
    parts: [],
  };
  state.messages.push(message);
  return message;
}

function appendAssistantText(state: TripUiState, text: string) {
  if (!text) return;
  const message = ensureAssistantMessage(state);
  const last = message.parts[message.parts.length - 1];
  if (last?.type === "text") {
    last.text += text;
  } else {
    message.parts.push({ type: "text", text });
  }
}

function appendTool(
  state: TripUiState,
  part: Omit<Extract<ChatPart, { type: "tool" }>, "type">,
) {
  const message = ensureAssistantMessage(state);
  message.parts.push({ type: "tool", ...part });
}

function finishTool(state: TripUiState, tool: string, label: string | null) {
  const message = ensureAssistantMessage(state);
  for (let i = message.parts.length - 1; i >= 0; i -= 1) {
    const part = message.parts[i];
    if (
      part.type === "tool" &&
      part.tool === tool &&
      part.status === "running" &&
      (!label || part.label === label)
    ) {
      part.status = "done";
      return;
    }
  }
}

function activeRunningNodeLabel(
  progress: Record<string, "running" | "done">,
  labels: Record<string, string>,
) {
  for (const node of Object.keys(progress)) {
    if (progress[node] === "running" && labels[node]) return labels[node];
  }
  return null;
}

function markRunningNodesDone(progress: Record<string, "running" | "done">) {
  return Object.fromEntries(
    Object.entries(progress).map(([node, status]) => [
      node,
      status === "running" ? "done" : status,
    ]),
  ) as Record<string, "running" | "done">;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
