"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/keys";

/**
 * The one query language (ADR-0016) — `q` is passed straight through to the
 * server. The dashboard never parses, validates, or extends it: a malformed
 * query comes back as a 422 problem response and is rendered as one.
 */
export function useSearch(query: string, cursor?: string) {
  return useQuery({
    queryKey: queryKeys.search(query, cursor),
    queryFn: async () => {
      const result = await apiClient.GET("/api/v1/search", {
        params: { query: { q: query, cursor, limit: 20 } },
      });
      return unwrap(result);
    },
    enabled: query.trim().length > 0,
  });
}
