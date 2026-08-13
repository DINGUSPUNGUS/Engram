/**
 * Query key factories for TanStack Query. One place names every cache
 * bucket, so `lib/sse/invalidation.ts` (what a pushed event invalidates)
 * and `lib/api/hooks/*` (what a fetch reads) can never drift from each
 * other's naming.
 *
 * Convention: singular root (`memory`, `proposal`) for the "one resource
 * and everything nested under it" family — invalidating `memory(id)`
 * invalidates its timeline and time-travel queries too, because TanStack
 * Query matches key arrays by prefix. Plural root (`memories`, `proposals`)
 * for list/search families, kept separate so a single-resource change
 * doesn't have to know every list-filter combination in flight.
 */

export interface MemoryListFilters {
  kind?: string;
  tag?: string;
  includeArchived?: boolean;
  includeStale?: boolean;
  cursor?: string;
}

export interface ProposalListFilters {
  status?: string;
  cursor?: string;
}

export const queryKeys = {
  stats: () => ["stats"] as const,
  settings: () => ["settings"] as const,

  memories: (filters?: MemoryListFilters) => ["memories", filters ?? {}] as const,
  memory: (id: string) => ["memory", id] as const,
  memoryTimeline: (id: string) => ["memory", id, "timeline"] as const,
  memoryAt: (id: string, selector: { version?: number; at?: string }) =>
    ["memory", id, "at", selector] as const,

  search: (query: string, cursor?: string) => ["search", query, cursor ?? null] as const,

  proposals: (filters?: ProposalListFilters) => ["proposals", filters ?? {}] as const,
  proposal: (id: string) => ["proposal", id] as const,
  proposalTimeline: (id: string) => ["proposal", id, "timeline"] as const,

  events: (after?: number) => ["events", after ?? 0] as const,
} as const;
