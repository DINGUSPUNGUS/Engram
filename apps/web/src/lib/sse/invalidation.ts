import type { QueryKey } from "@tanstack/react-query";

import { queryKeys } from "@/lib/api/keys";

/** The minimal shape `invalidationKeysFor` needs — a subset of `EventResponse`,
 * not the whole thing, so tests can construct one without the full wire shape. */
export interface InvalidationEvent {
  event_type: string;
  stream_id: string;
}

/**
 * Pure mapping from "an event was appended" to "these queries are stale."
 * This is the entire client-side reaction to a pushed event (ADR-0023 §2):
 * no folding, no state reconstruction — just naming what to re-fetch through
 * the normal read endpoints. Kept as a standalone function (not inline in
 * the SSE provider) so it can be unit-tested without a real EventSource.
 *
 * Deliberately over-invalidates rather than under-invalidates: a stream_id
 * is a memory id for `Memory*` events and a proposal id for `Proposal*`
 * events, so the specific resource always gets invalidated by id, and the
 * list/search families invalidate in full rather than trying to guess
 * which page or filter combination the event affects. ADR-0023's own
 * consequence #4 accepts this trade — "an extra request per change" — for
 * a local-first single-user system where that request is cheap.
 */
export function invalidationKeysFor(event: InvalidationEvent): QueryKey[] {
  const keys: QueryKey[] = [queryKeys.stats(), queryKeys.events()];

  if (event.event_type.startsWith("Memory")) {
    keys.push(queryKeys.memory(event.stream_id), queryKeys.memories());
    // A memory event can also change what full-text/attribute search
    // returns for any query — search results have no narrower key to
    // target, so the whole search family is treated as stale.
    keys.push(["search"]);
  } else if (event.event_type.startsWith("Proposal")) {
    keys.push(queryKeys.proposal(event.stream_id), queryKeys.proposals());
  }

  return keys;
}

/** Sentinel the stream sends when a reconnect gap exceeds the replay cap
 * (ADR-0023 §3) — "re-read from scratch" rather than a partial history. */
export const RESYNC_EVENT_NAME = "resync";
