import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import type { TripUiState } from "@/lib/types";
import { TripArtifact } from "./trip-artifact";

const baseState: TripUiState = {
  threadId: null,
  messages: [],
  dayPlans: [],
  budget: null,
  planVersion: 0,
  artifactOpen: true,
  activeDay: null,
  activePoiId: null,
  nodeProgress: {},
  nodeLabels: {},
  activeNodeLabel: null,
  loading: false,
  error: null,
};

const renderTripArtifact = (state: TripUiState) =>
  render(
    <TooltipProvider>
      <TripArtifact
        state={state}
        onClose={() => undefined}
        onSelectDay={() => undefined}
        onSelectPoi={() => undefined}
      />
    </TooltipProvider>,
  );

describe("TripArtifact", () => {
  it("does not reuse empty poi ids as route item keys", () => {
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);

    try {
      renderTripArtifact({
        ...baseState,
        dayPlans: [
          {
            day: 1,
            items: [
              { type: "attraction", name: "陈家祠", poi_id: "" },
              { type: "attraction", name: "广州塔", poi_id: "" },
            ],
          },
        ],
      });

      const duplicateKeyWarning = consoleError.mock.calls.find((args) =>
        args.join(" ").includes("Encountered two children with the same key"),
      );

      expect(screen.getByText("陈家祠")).toBeVisible();
      expect(screen.getByText("广州塔")).toBeVisible();
      expect(duplicateKeyWarning).toBeUndefined();
    } finally {
      consoleError.mockRestore();
    }
  });
});
