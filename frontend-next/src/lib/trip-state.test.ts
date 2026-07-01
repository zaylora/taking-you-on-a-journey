import { describe, expect, it } from "vitest";

import { applyTripEvent, createInitialTripState } from "./trip-state";

describe("trip state reducer", () => {
  it("streams assistant text into a single assistant message", () => {
    let state = createInitialTripState();

    state = applyTripEvent(state, { event: "token", data: { text: "你好" } });
    state = applyTripEvent(state, { event: "token", data: { text: "广州" } });

    expect(state.messages).toEqual([
      {
        id: "assistant-1",
        role: "assistant",
        parts: [{ type: "text", text: "你好广州" }],
      },
    ]);
  });

  it("records tool steps between text parts", () => {
    let state = createInitialTripState();

    state = applyTripEvent(state, {
      event: "tool_call",
      data: { tool: "research_xhs_travel_guide", label: "正在检索攻略" },
    });
    state = applyTripEvent(state, {
      event: "tool_result",
      data: { tool: "research_xhs_travel_guide", label: "正在检索攻略" },
    });

    expect(state.messages[0].parts).toEqual([
      {
        type: "tool",
        tool: "research_xhs_travel_guide",
        label: "正在检索攻略",
        status: "done",
      },
    ]);
  });

  it("opens the artifact when final day plans arrive", () => {
    let state = createInitialTripState();

    state = applyTripEvent(state, {
      event: "final",
      data: {
        answer: "这是行程",
        day_plans: [{ day: 1, items: [], center: { lng: 113.26, lat: 23.13 } }],
        budget: { estimated: 1200 },
        plan_version: 3,
      },
    });

    expect(state.artifactOpen).toBe(true);
    expect(state.dayPlans).toHaveLength(1);
    expect(state.planVersion).toBe(3);
  });
});

