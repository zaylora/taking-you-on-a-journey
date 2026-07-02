import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TripChatApp } from "./trip-chat-app";
import { fetchTripChatStream } from "@/lib/sse";
import { TooltipProvider } from "@/components/ui/tooltip";

const renderTripChatApp = (ui: React.ReactElement) =>
  render(<TooltipProvider>{ui}</TooltipProvider>);

vi.mock("@/lib/sse", () => ({
  fetchTripChatStream: vi.fn(async () => undefined),
}));

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("TripChatApp", () => {
  it("loads backend sessions and restores the latest conversation history", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/sessions")) {
        return jsonResponse({
          sessions: [
            {
              thread_id: "thread-1",
              title: "广州亲子游",
              created_at: "2026-07-01T10:00:00Z",
              updated_at: "2026-07-01T10:30:00Z",
            },
          ],
        });
      }
      if (url.endsWith("/api/sessions/thread-1")) {
        return jsonResponse({
          thread_id: "thread-1",
          title: "广州亲子游",
          created_at: "2026-07-01T10:00:00Z",
          updated_at: "2026-07-01T10:30:00Z",
          messages: [
            {
              role: "user",
              content: "第一轮：广州三天",
              kind: "text",
              segments: [{ kind: "text", text: "第一轮：广州三天" }],
            },
            {
              role: "assistant",
              content: "可以安排老城和珠江。",
              kind: "text",
              segments: [{ kind: "text", text: "可以安排老城和珠江。" }],
            },
          ],
          day_plans: [],
          budget: {},
          plan_version: 0,
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderTripChatApp(<TripChatApp />);

    const sessionNav = await screen.findByRole("navigation", { name: "历史会话" });
    expect(sessionNav.closest("aside")).not.toBeNull();
    expect(screen.getByRole("button", { name: "广州亲子游" })).toBeVisible();
    expect(screen.getByText("第一轮：广州三天")).toBeVisible();
    expect(screen.getByText("可以安排老城和珠江。")).toBeVisible();
    expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([
      "http://localhost:8000/api/sessions",
      "http://localhost:8000/api/sessions/thread-1",
    ]);
  });

  it("shows the route artifact when initial day plans exist", () => {
    renderTripChatApp(
      <TripChatApp
        initialState={{
          dayPlans: [
            {
              day: 1,
              items: [
                {
                  type: "attraction",
                  name: "陈家祠",
                  poi_id: "B001",
                  location: { lng: 113.249, lat: 23.125 },
                },
              ],
              center: { lng: 113.26, lat: 23.13 },
              weather: {
                text: "晴",
                temp: "28℃",
                is_rainy: false,
                source: "amap",
              },
            },
          ],
          artifactOpen: true,
        }}
      />,
    );

    expect(screen.getByRole("complementary", { name: "行程工作区" })).toBeVisible();
    expect(screen.getByTestId("trip-artifact-motion")).toHaveAttribute(
      "data-state",
      "open",
    );
    expect(screen.getByTestId("ai-elements-artifact")).toBeVisible();
    expect(screen.getByRole("heading", { name: "行程地图" })).toBeVisible();
    expect(screen.getByText("1 天路线")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Day 1" })).toBeVisible();
    expect(screen.getByText("陈家祠")).toBeVisible();
  });

  it("toggles the history sidebar from the chat header", () => {
    renderTripChatApp(<TripChatApp initialState={{}} />);

    expect(
      screen.getByRole("navigation", { name: "历史会话" }),
    ).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "显示隐藏历史会话" }));
    expect(
      screen.queryByRole("navigation", { name: "历史会话" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "显示隐藏历史会话" }));
    expect(
      screen.getByRole("navigation", { name: "历史会话" }),
    ).toBeVisible();
  });

  it("sends the visible conversation history with the next message", async () => {
    renderTripChatApp(
      <TripChatApp
        initialState={{
          threadId: "thread-1",
          messages: [
            {
              id: "user-1",
              role: "user",
              parts: [{ type: "text", text: "我想去广州" }],
            },
            {
              id: "assistant-1",
              role: "assistant",
              parts: [{ type: "text", text: "可以安排三天两晚。" }],
            },
          ],
        }}
      />,
    );

    fireEvent.change(screen.getByLabelText("发送消息"), {
      target: { value: "第二轮：加亲子活动" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => expect(fetchTripChatStream).toHaveBeenCalled());
    expect(fetchTripChatStream).toHaveBeenCalledWith(
      expect.objectContaining({
        message: "第二轮：加亲子活动",
        threadId: "thread-1",
        messages: [
          {
            id: "user-1",
            role: "user",
            parts: [{ type: "text", text: "我想去广州" }],
          },
          {
            id: "assistant-1",
            role: "assistant",
            parts: [{ type: "text", text: "可以安排三天两晚。" }],
          },
          {
            id: "user-3",
            role: "user",
            parts: [{ type: "text", text: "第二轮：加亲子活动" }],
          },
        ],
      }),
      expect.any(Function),
      expect.any(AbortSignal),
    );
  });
});

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
