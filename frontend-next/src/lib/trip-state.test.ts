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

  it("tracks node start and end labels for the transient thinking state", () => {
    let state = createInitialTripState();

    state = applyTripEvent(state, {
      event: "node_start",
      data: { node: "model", label: "正在思考..." },
    });

    expect(state.activeNodeLabel).toBe("正在思考...");
    expect(state.nodeProgress.model).toBe("running");

    state = applyTripEvent(state, {
      event: "node_end",
      data: { node: "model" },
    });

    expect(state.activeNodeLabel).toBeNull();
    expect(state.nodeProgress.model).toBe("done");
  });

  it("finishes the matching repeated tool call by label", () => {
    let state = createInitialTripState();

    state = applyTripEvent(state, {
      event: "tool_call",
      data: { tool: "search_restaurants", label: "搜索广州餐厅：陶陶居" },
    });
    state = applyTripEvent(state, {
      event: "tool_call",
      data: { tool: "search_restaurants", label: "搜索广州餐厅：点都德" },
    });
    state = applyTripEvent(state, {
      event: "tool_result",
      data: { tool: "search_restaurants", label: "搜索广州餐厅：点都德" },
    });

    expect(state.messages[0].parts).toEqual([
      {
        type: "tool",
        tool: "search_restaurants",
        label: "搜索广州餐厅：陶陶居",
        status: "running",
      },
      {
        type: "tool",
        tool: "search_restaurants",
        label: "搜索广州餐厅：点都德",
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
