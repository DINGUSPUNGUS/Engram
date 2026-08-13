"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { type MemoryListFilters, queryKeys } from "@/lib/api/keys";

/**
 * Memory Explorer's data layer. Every function here is parse-params →
 * one `@engram/api-client` call → typed result; no folding, no derived
 * confidence, no decisions — those all happen server-side (ADR-0021 §1).
 */

export function useMemories(filters: MemoryListFilters = {}) {
  return useQuery({
    queryKey: queryKeys.memories(filters),
    queryFn: async () => {
      const result = await apiClient.GET("/api/v1/memories", {
        params: {
          query: {
            kind: filters.kind as never,
            tag: filters.tag,
            include_archived: filters.includeArchived,
            include_stale: filters.includeStale,
            cursor: filters.cursor,
          },
        },
      });
      return unwrap(result);
    },
  });
}

export function useMemory(memoryId: string | undefined) {
  const id = memoryId ?? "";
  return useQuery({
    queryKey: queryKeys.memory(id),
    // `enabled` gates whether this ever runs — an empty id here never
    // reaches the network, so a fallback is safe and avoids `memoryId!`.
    queryFn: async () => {
      const result = await apiClient.GET("/api/v1/memories/{memory_id}", {
        params: { path: { memory_id: id } },
      });
      return unwrap(result);
    },
    enabled: memoryId !== undefined,
  });
}

export function useMemoryTimeline(memoryId: string | undefined) {
  const id = memoryId ?? "";
  return useQuery({
    queryKey: queryKeys.memoryTimeline(id),
    queryFn: async () => {
      const result = await apiClient.GET("/api/v1/memories/{memory_id}/timeline", {
        params: { path: { memory_id: id } },
      });
      return unwrap(result);
    },
    enabled: memoryId !== undefined,
  });
}

/** Time travel (ADR-0002/ADR-0021): exactly one of version/at, chosen by the caller. */
export function useMemoryAt(
  memoryId: string | undefined,
  selector: { version?: number; at?: string },
  options?: { enabled?: boolean },
) {
  const id = memoryId ?? "";
  return useQuery({
    queryKey: queryKeys.memoryAt(id, selector),
    queryFn: async () => {
      const result = await apiClient.GET("/api/v1/memories/{memory_id}/at", {
        params: {
          path: { memory_id: id },
          query: { version: selector.version, at: selector.at },
        },
      });
      return unwrap(result);
    },
    enabled:
      memoryId !== undefined &&
      (selector.version !== undefined || selector.at !== undefined) &&
      (options?.enabled ?? true),
  });
}

function useMemoryMutation<TArgs extends { memoryId: string }, TData>(
  mutationFn: (args: TArgs) => Promise<TData>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.memory(variables.memoryId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.memories() });
    },
  });
}

/** Vouch for a memory: raises confidence, resets staleness (the spine's positive signal). */
export function useConfirmMemory() {
  return useMemoryMutation(async ({ memoryId, note }: { memoryId: string; note?: string }) => {
    const result = await apiClient.POST("/api/v1/memories/{memory_id}/confirm", {
      params: { path: { memory_id: memoryId } },
      body: { note: note ?? null },
    });
    return unwrap(result);
  });
}

/** Dispute a memory: lowers confidence (the spine's negative signal). */
export function useContradictMemory() {
  return useMemoryMutation(
    async ({
      memoryId,
      contradictingId,
      note,
    }: {
      memoryId: string;
      contradictingId?: string;
      note?: string;
    }) => {
      const result = await apiClient.POST("/api/v1/memories/{memory_id}/contradict", {
        params: { path: { memory_id: memoryId } },
        body: { contradicting_id: contradictingId ?? null, note: note ?? null },
      });
      return unwrap(result);
    },
  );
}

/** Append supporting evidence — additive, never edits or removes prior evidence. */
export function useAddEvidence() {
  return useMemoryMutation(
    async ({
      memoryId,
      evidenceType,
      value,
      note,
    }: {
      memoryId: string;
      evidenceType: string;
      value: string;
      note?: string;
    }) => {
      const result = await apiClient.POST("/api/v1/memories/{memory_id}/evidence", {
        params: { path: { memory_id: memoryId } },
        body: { evidence_type: evidenceType as never, value, note: note ?? null },
      });
      return unwrap(result);
    },
  );
}

/** Pin/unpin, or set an explicit weight — the spine's importance half. */
export function useAdjustImportance() {
  return useMemoryMutation(
    async ({
      memoryId,
      pinned,
      userWeight,
    }: {
      memoryId: string;
      pinned?: boolean;
      userWeight?: number;
    }) => {
      const result = await apiClient.PATCH("/api/v1/memories/{memory_id}/importance", {
        params: { path: { memory_id: memoryId } },
        body: { pinned: pinned ?? null, user_weight: userWeight ?? null },
      });
      return unwrap(result);
    },
  );
}

/** Compensate the memory's most recent change (ADR-0021). 409 if it has no inverse. */
export function useUndoMemory() {
  return useMemoryMutation(async ({ memoryId }: { memoryId: string }) => {
    const result = await apiClient.POST("/api/v1/memories/{memory_id}/undo", {
      params: { path: { memory_id: memoryId } },
    });
    return unwrap(result);
  });
}
