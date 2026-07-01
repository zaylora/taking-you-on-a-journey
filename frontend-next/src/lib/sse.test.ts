import { describe, expect, it, vi } from "vitest";

import { fetchTripChatStream, parseSseChunk } from "./sse";

describe("parseSseChunk", () => {
  it("parses named FastAPI SSE frames and keeps incomplete tails", () => {
    const chunk =
      'event: token\ndata: {"text":"广州"}\n\n' +
      'event: final\ndata: {"answer":"完成","day_plans":[{"day":1,"items":[]}],"plan_version":2}\n\n' +
      "event: token\n";

    const result = parseSseChunk(chunk);

    expect(result.events).toEqual([
      { event: "token", data: { text: "广州" } },
      {
        event: "final",
        data: {
          answer: "完成",
          day_plans: [{ day: 1, items: [] }],
          plan_version: 2,
        },
      },
    ]);
    expect(result.remainder).toBe("event: token\n");
  });
});

describe("fetchTripChatStream", () => {
  it("posts the existing backend chat contract and emits parsed events", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          encoder.encode('event: token\ndata: {"text":"你好"}\n\n'),
        );
        controller.enqueue(
          encoder.encode('event: final\ndata: {"answer":"好了"}\n\n'),
        );
        controller.close();
      },
    });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: stream,
    });

    const events: Array<{ event: string; data: unknown }> = [];
    await fetchTripChatStream(
      {
        message: "规划广州三日游",
        threadId: "thread-1",
        baseUrl: "http://api.test",
      },
      (event, data) => events.push({ event, data }),
      undefined,
      fetchMock,
    );

    expect(fetchMock).toHaveBeenCalledWith("http://api.test/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: "规划广州三日游",
        thread_id: "thread-1",
      }),
      signal: undefined,
    });
    expect(events).toEqual([
      { event: "token", data: { text: "你好" } },
      { event: "final", data: { answer: "好了" } },
    ]);
  });
});

