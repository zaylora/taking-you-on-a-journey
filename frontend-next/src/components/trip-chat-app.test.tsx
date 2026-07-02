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
});

describe("TripChatApp", () => {
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
    expect(screen.getByTestId("ai-elements-artifact")).toBeVisible();
    expect(screen.getByRole("heading", { name: "行程地图" })).toBeVisible();
    expect(screen.getByText("1 天路线")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Day 1" })).toBeVisible();
    expect(screen.getByText("陈家祠")).toBeVisible();
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
