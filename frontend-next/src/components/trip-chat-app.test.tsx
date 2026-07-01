import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TripChatApp } from "./trip-chat-app";

describe("TripChatApp", () => {
  it("shows the route artifact when initial day plans exist", () => {
    render(
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
    expect(screen.getByRole("heading", { name: "Day 1" })).toBeVisible();
    expect(screen.getByText("陈家祠")).toBeVisible();
  });
});
