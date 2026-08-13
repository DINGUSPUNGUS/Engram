"use client";

import Link from "next/link";

import { ProvenancePanel } from "@/components/provenance";
import { QueryState } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useProposal, useProposalTimeline } from "@/lib/api/hooks/proposals";
import { draftTargetId } from "@/lib/drafts";
import { formatDateTime } from "@/lib/format";

export function ObservatoryProposalPage({ proposalId }: { proposalId: string }) {
  const proposal = useProposal(proposalId);
  const timeline = useProposalTimeline(proposalId);

  const openedEntry = timeline.data?.entries.find((entry) => entry.event_type === "ProposalOpened");

  return (
    <div className="flex flex-col gap-6">
      <QueryState query={proposal}>
        {(data) => (
          <>
            <header>
              <p className="text-sm text-muted-foreground">Observatory · proposal</p>
              <h1 className="text-2xl font-semibold tracking-tight">{data.title}</h1>
              <Link href={`/proposals/${proposalId}`} className="text-sm hover:underline">
                View in Proposal Review →
              </Link>
            </header>

            <Card>
              <CardHeader>
                <CardTitle>Why this was proposed</CardTitle>
                <CardDescription>
                  The full pipeline explanation, if the opening actor recorded one (ADR-0019 §3) —
                  provider, model, prompt versions, extraction and scoring, verbatim.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {timeline.isPending ? (
                  <p className="text-sm text-muted-foreground">Loading…</p>
                ) : openedEntry ? (
                  <ProvenancePanel provenance={openedEntry.provenance} />
                ) : (
                  <p className="text-sm italic text-muted-foreground">
                    No ProposalOpened event found on this stream — unavailable.
                  </p>
                )}
              </CardContent>
            </Card>

            {data.status === "merged" ? (
              <Card>
                <CardHeader>
                  <CardTitle>What it produced</CardTitle>
                  <CardDescription>
                    {(data.merged_event_ids ?? []).length} event
                    {(data.merged_event_ids ?? []).length === 1 ? "" : "s"} appended. Memories
                    drafted by this proposal:
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <ul className="flex flex-col gap-1">
                    {[
                      ...new Set(
                        (data.drafts ?? [])
                          .map(draftTargetId)
                          .filter((id): id is string => Boolean(id)),
                      ),
                    ].map((memoryId) => (
                      <li key={memoryId}>
                        <Link
                          href={`/observatory/memories/${memoryId}`}
                          className="text-sm hover:underline"
                        >
                          {memoryId}
                        </Link>
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            ) : null}
          </>
        )}
      </QueryState>

      <Card>
        <CardHeader>
          <CardTitle>Full lifecycle</CardTitle>
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
