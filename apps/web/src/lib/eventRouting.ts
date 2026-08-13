/**
 * Every event's `stream_id` is either a memory id or a proposal id — which
 * one is inherent in the already-public `event_type` string (`Memory*` /
 * `Proposal*`), not something the dashboard decides. Shared by Home,
 * Timeline, and Observatory so "where does this event link to" is answered
 * once, not reimplemented per screen.
 */
export function streamHref(eventType: string, streamId: string): string | null {
  if (eventType.startsWith("Memory")) return `/memories/${streamId}`;
  if (eventType.startsWith("Proposal")) return `/proposals/${streamId}`;
  return null;
}

export function streamKind(eventType: string): "memory" | "proposal" | "unknown" {
  if (eventType.startsWith("Memory")) return "memory";
  if (eventType.startsWith("Proposal")) return "proposal";
  return "unknown";
}
