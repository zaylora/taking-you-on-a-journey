import * as React from "react";

import { cn } from "@/lib/utils";

type BadgeVariant = "default" | "secondary";

export function Badge({
  className,
  variant = "default",
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { variant?: BadgeVariant }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium",
        variant === "secondary"
          ? "border-border bg-secondary text-secondary-foreground"
          : "border-zinc-200 bg-zinc-50 text-zinc-700",
        className,
      )}
      {...props}
    />
  );
}
