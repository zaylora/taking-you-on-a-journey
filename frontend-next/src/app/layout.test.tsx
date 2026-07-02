import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";

import RootLayout from "./layout";

describe("RootLayout", () => {
  it("applies the dark theme at the document root", () => {
    const tree = RootLayout({
      children: <main />,
    }) as ReactElement<{ className?: string }>;

    expect(tree.props.className).toContain("dark");
  });
});
