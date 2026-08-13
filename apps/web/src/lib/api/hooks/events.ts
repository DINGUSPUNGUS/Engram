"use client";

import type { components } from "@engram/api-client";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useStats } from "@/lib/api/hooks/system";
import { queryKeys } from "@/lib/api/keys";

type EventResponse = components["schemas"]["EventResponse"];

/**
 * The paginated audit feed (`GET /api/v1/events`) — Timeline and Console's
 * data source. This is a read of the raw log, not a projection; payloads
 * are omitted by the server (ADR-0023 §2), which is why event rows here
 * only ever show what happened and who, never the memory content itself.
 */
export function useEventFeed(after: number | undefined, limit = 50, enabled = true) {
  return useQuery({
    queryKey: queryKeys.events(after),
    queryFn: async () => {
      const result = await apiClient.GET("/api/v1/events", {
        params: { query: { after: after ?? 0, limit } },
      });
      return unwrap(result);
    },
    enabled,
  });
}

/**
 * The most recent `limit` events, newest first — Home's "recent activity"
 * and nothing more exotic: the feed is only ever readable ascending by
 * `global_seq`, so this reads from `head - limit` (via `/stats`, whose
 * `head_global_seq` is exactly `MAX(global_seq)` — a dense counter, so the
 * page is exact, not approximate) and reverses it for display.
 */
interface RecentEventsResult {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  data: { items: EventResponse[] } | undefined;
  refetch: () => void;
}

export function useRecentEvents(limit = 10): RecentEventsResult {
  const stats = useStats();
  const head = stats.data?.head_global_seq;
  const feed = useEventFeed(
    head !== undefined ? Math.max(0, head - limit) : undefined,
    limit,
    head !== undefined,
  );

  if (stats.isError) {
    return {
      isPending: false,
      isError: true,
      error: stats.error,
      data: undefined,
      refetch: stats.refetch,
    };
  }
  return {
    isPending: stats.isPending || feed.isPending,
    isError: feed.isError,
    error: feed.error,
    data: feed.data ? { items: [...feed.data.items].reverse() } : undefined,
    refetch: feed.refetch,
  };
}
