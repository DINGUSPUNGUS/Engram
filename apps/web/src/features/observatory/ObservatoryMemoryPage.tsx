"use client";

import { Search } from "lucide-react";
import Link from "next/link";

import { ProvenancePanel } from "@/components/provenance";
import { ErrorState, QueryState } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SEARCH_WINDOW, useFindOriginProposal } from "@/features/observatory/findOrigin";
import { useMemory, useMemoryTimeline } from "@/lib/api/hooks/memories";
import { formatDateTime } from "@/lib/format";

export function ObservatoryMemoryPage({ memoryId }: { memoryId: string }) {
  const memory = useMemory(memoryId);
  const timeline = useMemoryTimeline(memoryId);
  const findOrigin = useFindOriginProposal();

  return (
    <div className="flex flex-col gap-6">
      <QueryState query={memory}>
        {(data) => (
          <header>
            <p className="text-sm text-muted-foreground">Observatory · memory</p>
            <h1 className="text-2xl font-semibold tracking-tight">{data.title}</h1>
            <Link href={`/memories/${memoryId}`} className="text-sm hover:underline">
              View in Memory Explorer →
            </Link>
          </header>
        )}
      </QueryState>

      <Card>
        <CardHeader>
          <CardTitle>Where did this come from?</CardTitle>
          <CardDescription>
            Merged events carry the reviewer's provenance, not the original proposer's — engram
            doesn't index event → proposal, so this is a bounded, on-demand search over existing
            reads, not a stored fact.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {findOrigin.data === undefined ? (
            <Button
              variant="outline"
              className="w-fit"
              disabled={findOrigin.isPending || !timeline.data}
              onClick={() =>
                timeline.data &&
                findOrigin.mutate({ memoryEventIds: timeline.data.entries.map((e) => e.event_id) })
              }
            >
              <Search className="h-4 w-4" />
              Search the {SEARCH_WINDOW} most recently merged proposals
            </Button>
          ) : findOrigin.data === null ? (
            <p className="text-sm text-muted-foreground">
              No origin found in the {SEARCH_WINDOW} most recently merged proposals. This memory may
              have been created directly (CLI/API), or its proposal is older than this search window
              — unavailable, not "none".
            </p>
          ) : (
            <p className="text-sm">
              Proposed via{" "}
              <Link
                href={`/observatory/proposals/${findOrigin.data.proposalId}`}
                className="font-medium hover:underline"
              >
                {findOrigin.data.proposalTitle}
              </Link>{" "}
              — open it for the full pipeline explanation.
            </p>
          )}
          {findOrigin.isError ? <ErrorState error={findOrigin.error} /> : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Event history &amp; provenance</CardTitle>
          <CardDescription>
            Every mover of this memory's state, in order — the durable half of "why."
          </CardDescription>
        </CardHeader>
        <CardContent>
          <QueryState query={timeline} isEmpty={(data) => data.entries.length === 0}>
            {(data) => (
              <ol className="flex flex-col gap-3">
                {data.entries.map((entry) => (
                  <li key={entry.event_id} className="rounded-md border border-border p-3">
                    <div className="flex items-center justify-between gap-2">
                      <Badge variant="outline">{entry.event_type}</Badge>
                      <span className="text-xs text-muted-foreground">
                        {formatDateTime(entry.occurred_at)}
                      </span>
                    </div>
                    <div className="mt-2">
                      <ProvenancePanel provenance={entry.provenance} />
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </QueryState>
        </CardContent>
      </Card>
    </div>
  );
}
