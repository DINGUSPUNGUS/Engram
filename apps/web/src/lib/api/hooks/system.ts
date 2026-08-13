"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/keys";

/** Home's space statistics and Console's health check — `GET /api/v1/stats`. */
export function useStats() {
  return useQuery({
    queryKey: queryKeys.stats(),
    queryFn: async () => unwrap(await apiClient.GET("/api/v1/stats", {})),
  });
}

/** Settings' read-only configuration — `GET /api/v1/settings`. */
export function useSettings() {
  return useQuery({
    queryKey: queryKeys.settings(),
    queryFn: async () => unwrap(await apiClient.GET("/api/v1/settings", {})),
  });
}

/**
 * Replay the log through every projection (`POST /admin/rebuild`) — the
 * disposability invariant, over HTTP. A rebuild changes nothing about the
 * log itself, so on success this refreshes every read model wholesale
 * rather than trying to guess which ones moved.
 */
export function useRebuild() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => unwrap(await apiClient.POST("/admin/rebuild", {})),
    onSuccess: () => {
      void queryClient.invalidateQueries();
    },
  });
}
