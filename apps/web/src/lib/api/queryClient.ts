import { QueryClient } from "@tanstack/react-query";

import { isApiError } from "@/lib/api/errors";

/**
 * One client per browser tab (created lazily in `Providers.tsx`). Defaults
 * assume the SSE invalidation flow (ADR-0023) is the primary freshness
 * mechanism, not polling or aggressive refetch-on-focus:
 *
 * - `staleTime` is short but nonzero: a query fetched a moment ago (e.g. by
 *   a sibling component reading the same memory) doesn't refetch twice.
 * - No retry on 4xx: a 404/409/422 is a real answer, not a transient
 *   failure — retrying it wastes a round trip and delays the error state.
 * - Retry once on 5xx/network errors, since those can be transient.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5_000,
        retry: (failureCount, error) => {
          if (isApiError(error) && error.status < 500) return false;
          return failureCount < 1;
        },
      },
      mutations: {
        retry: false,
      },
    },
  });
}
