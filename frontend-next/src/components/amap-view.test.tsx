import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AmapView } from "./amap-view";

describe("AmapView", () => {
  it("shows a configuration hint when the browser map key is missing", () => {
    render(
      <AmapView
        dayPlans={[
          {
            day: 1,
            items: [],
            center: { lng: 113.26, lat: 23.13 },
          },
        ]}
        activeDay={null}
        activePoiId={null}
        onSelectPoi={() => undefined}
      />,
    );

    expect(screen.getByText("未配置高德地图 Key")).toBeVisible();
  });
});

