"use client";

import { CircleDot, RefreshCw, WifiOff } from "lucide-react";

import { useEventStreamStatus } from "@/lib/sse/EventStreamProvider";

const LABEL: Record<string, string> = {
  connecting: "Connecting…",
  open: "Live",
  reconnecting: "Reconnecting…",
  unavailable: "Offline — data may be stale",
};

/**
 * Live/offline indicator for the one shared SSE connection (ADR-0023).
 * Exists so staleness is a visible property of the UI, not a silent risk —
 * when this reads "Offline", views are still correct as of their last
 * fetch, they just won't hear about new changes until the connection (or a
 * manual refresh) comes back.
 */
export function ConnectionBadge() {
  const status = useEventStreamStatus();

  const icon =
    status === "open" ? (
      <CircleDot aria-hidden="true" className="h-3 w-3 text-emerald-500" />
    ) : status === "unavailable" ? (
      <WifiOff aria-hidden="true" className="h-3 w-3 text-destructive" />
    ) : (
      <RefreshCw aria-hidden="true" className="h-3 w-3 animate-spin text-amber-500" />
    );

  return (
    <output className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      {icon}
      {LABEL[status]}
    </output>
  );
}
