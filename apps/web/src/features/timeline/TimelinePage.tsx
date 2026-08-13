"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ProvenancePanel } from "@/components/provenance";
import { EmptyState, ErrorState, LoadingState } from "@/components/status";
import { Button } from "@/components/ui/button";
import { useEventFeed } from "@/lib/api/hooks/events";
import { useMemoryTimeline } from "@/lib/api/hooks/memories";
import { useProposalTimeline } from "@/lib/api/hooks/proposals";
import { streamHref, streamKind } from "@/lib/eventRouting";
import { formatDateTime } from "@/lib/format";

/**
 * The chronological event stream — the log itself, oldest first, exactly as
 * `GET /api/v1/events` orders it. Live updates arrive as SSE invalidation
 * signals (ADR-0023): a push never appends a row directly, it marks this
 * page's query stale and the next render re-fetches through the same
 * endpoint, so what's on screen is always what a fresh load would show.
 */
export function TimelinePage() {
  const [after, setAfter] = useState(0);
  const feed = useEventFeed(after, 50);
  const data = feed.data;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Timeline</h1>
        <p className="text-muted-foreground">
          Every event, in the order it was appended to the log.
        </p>
      </div>

      {feed.isPending ? <LoadingState /> : null}
      {feed.isError ? <ErrorState error={feed.error} onRetry={feed.refetch} /> : null}
      {data && data.items.length === 0 ? <EmptyState title="No events yet" /> : null}
      {data && data.items.length > 0 ? (
        <>
          <ol className="flex flex-col divide-y divide-border rounded-lg border border-border">
            {data.items.map((event) => (
              <EventRow key={event.event_id} event={event} />
            ))}
          </ol>
          {data.next_after !== null && data.next_after !== undefined ? (
            <Button
              variant="outline"
              className="w-fit"
              onClick={() => setAfter(data.next_after ?? 0)}
            >
              Load more
            </Button>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

interface FeedEvent {
  event_id: string;
  event_type: string;
  stream_id: string;
  stream_seq: number;
  global_seq: number;
  occurred_at: string;
  actor: string;
}

function EventRow({ event }: { event: FeedEvent }) {
  const [expanded, setExpanded] = useState(false);
  const href = streamHref(event.event_type, event.stream_id);
  const kind = streamKind(event.event_type);

  return (
    <li className="p-3">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className="text-muted-foreground hover:text-foreground"
        >
          {expanded ? (
            <ChevronDown aria-hidden="true" className="h-4 w-4" />
          ) : (
            <ChevronRight aria-hidden="true" className="h-4 w-4" />
          )}
          <span className="sr-only">Toggle details</span>
        </button>
        <span className="font-mono text-xs text-muted-foreground">#{event.global_seq}</span>
        <span className="font-medium">{event.event_type}</span>
        <span className="text-sm text-muted-foreground">by {event.actor}</span>
        <time dateTime={event.occurred_at} className="ml-auto text-xs text-muted-foreground">
          {formatDateTime(event.occurred_at)}
        </time>
      </div>
      {expanded ? (
        <div className="ml-6 mt-2 flex flex-col gap-2">
          {href ? (
            <Link href={href} className="w-fit text-sm hover:underline">
              View {kind} →
            </Link>
          ) : null}
          <EventDetails event={event} kind={kind} />
        </div>
      ) : null}
    </li>
  );
}

/** The paginated feed omits full provenance (only `actor`); full
 * `session_id`/`detail` lives on the owning stream's timeline. This
 * composes two existing reads rather than asking the backend for a new
 * "event detail" endpoint. */
function EventDetails({
  event,
  kind,
}: {
  event: FeedEvent;
  kind: "memory" | "proposal" | "unknown";
}) {
  const memoryTimeline = useMemoryTimeline(kind === "memory" ? event.stream_id : undefined);
  const proposalTimeline = useProposalTimeline(kind === "proposal" ? event.stream_id : undefined);

  if (kind === "unknown") {
    return (
      <p className="text-sm text-muted-foreground">
        No provenance detail available for this event type.
      </p>
    );
  }

  const timeline = kind === "memory" ? memoryTimeline : proposalTimeline;
  if (timeline.isPending) return <LoadingState rows={1} />;
  if (timeline.isError) return <ErrorState error={timeline.error} />;

  const entry = timeline.data?.entries.find((candidate) => candidate.event_id === event.event_id);
  if (!entry) {
    return (
      <p className="text-sm text-muted-foreground">
        Provenance unavailable — not found on the owning stream.
      </p>
    );
  }

  return <ProvenancePanel provenance={entry.provenance} />;
}
