export interface ParsedSseEvent {
  event: string;
  data: unknown;
}

export interface ParsedSseChunk {
  events: ParsedSseEvent[];
  remainder: string;
}

export interface FetchTripChatStreamInput {
  message: string;
  threadId: string | null;
  baseUrl?: string;
}

type FetchLike = typeof fetch;

const defaultBaseUrl = () =>
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export function parseSseChunk(text: string): ParsedSseChunk {
  const frames = text.split(/\r?\n\r?\n/);
  const remainder = frames.pop() ?? "";
  const events: ParsedSseEvent[] = [];

  for (const frame of frames) {
    if (!frame.trim()) continue;
    let event = "message";
    const dataLines: string[] = [];

    for (const line of frame.split(/\r?\n/)) {
      if (line.startsWith(":")) continue;
      if (line.startsWith("event:")) {
        event = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }

    if (!dataLines.length) continue;
    const rawData = dataLines.join("\n");
    try {
      events.push({ event, data: JSON.parse(rawData) });
    } catch {
      events.push({ event, data: rawData });
    }
  }

  return { events, remainder };
}

export async function fetchTripChatStream(
  input: FetchTripChatStreamInput,
  onEvent: (event: string, data: unknown) => void,
  signal?: AbortSignal,
  fetchImpl: FetchLike = fetch,
) {
  const response = await fetchImpl(`${input.baseUrl ?? defaultBaseUrl()}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: input.message,
      thread_id: input.threadId,
    }),
    signal,
  });

  if (!response.ok) {
    throw new Error(`HTTP error ${response.status}`);
  }
  if (!response.body) {
    throw new Error("Response body is empty");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const parsed = parseSseChunk(buffer);
    buffer = parsed.remainder;
    for (const item of parsed.events) {
      onEvent(item.event, item.data);
    }
  }
}

