"use client";

import { useQueryClient } from "@tanstack/react-query";
import { createContext, type ReactNode, useContext, useEffect, useState } from "react";

import { API_BASE_URL } from "@/lib/api/client";
import { invalidationKeysFor, RESYNC_EVENT_NAME } from "@/lib/sse/invalidation";

export type StreamStatus = "connecting" | "open" | "reconnecting" | "unavailable";

const EventStreamContext = createContext<StreamStatus>("connecting");

/** Read by `ConnectionBadge` and any view that wants to show staleness risk
 * explicitly (the TESTING list's "stale data" requirement) rather than
 * silently trusting a dead connection. */
export function useEventStreamStatus(): StreamStatus {
  return useContext(EventStreamContext);
}

/**
 * One `EventSource` per dashboard session, opened here and shared by every
 * view (ADR-0023 §5 — "one stream per dashboard session, shared across
 * views, not one per component"). Every message it receives is treated as
 * an invalidation signal only: `invalidationKeysFor` says which cached
 * reads are now stale, and TanStack Query re-fetches them through the
 * normal HTTP endpoints. Nothing here folds a pushed payload into state —
 * there is no payload to fold; the server omits it by design.
 *
 * Reconnection is the browser's own `EventSource` behavior: it remembers
 * the last `id:` field it saw and resends it as `Last-Event-ID` on
 * reconnect automatically, which is what lets the server replay exactly
 * the missed range (ADR-0023 §3). Nothing here has to implement that.
 */
export function EventStreamProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<StreamStatus>("connecting");

  useEffect(() => {
    if (typeof EventSource === "undefined") {
      setStatus("unavailable");
      return;
    }

    const source = new EventSource(`${API_BASE_URL}/api/v1/events/stream`);
    let everOpened = false;

    source.onopen = () => {
      everOpened = true;
      setStatus("open");
    };

    source.onerror = () => {
      // EventSource retries on its own; this only reports it. A drop before
      // the first successful open is a real failure, not a reconnect.
      setStatus(everOpened ? "reconnecting" : "unavailable");
    };

    source.onmessage = (message: MessageEvent<string>) => {
      let event: { event_type?: unknown; stream_id?: unknown };
      try {
        event = JSON.parse(message.data) as typeof event;
      } catch {
        return; // malformed frame — nothing to invalidate, nothing to crash on
      }
      if (typeof event.event_type !== "string" || typeof event.stream_id !== "string") return;
      for (const key of invalidationKeysFor({
        event_type: event.event_type,
        stream_id: event.stream_id,
      })) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
    };

    source.addEventListener(RESYNC_EVENT_NAME, () => {
      // Gap exceeded the server's replay cap (ADR-0023 §3): no partial
      // history was sent, so every cached read is now potentially stale.
      void queryClient.invalidateQueries();
    });

    return () => source.close();
  }, [queryClient]);

  return <EventStreamContext.Provider value={status}>{children}</EventStreamContext.Provider>;
}
