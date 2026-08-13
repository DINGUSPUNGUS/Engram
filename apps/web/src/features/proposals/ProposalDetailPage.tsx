"use client";

import { CheckCircle2, GitMerge, History, Undo2, XCircle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ProvenancePanel } from "@/components/provenance";
import { ErrorState, QueryState } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  useApproveProposal,
  useMergeProposal,
  useProposal,
  useProposalTimeline,
  useRejectProposal,
  useUndoProposal,
} from "@/lib/api/hooks/proposals";
import { draftTargetId } from "@/lib/drafts";
import { formatDateTime } from "@/lib/format";

const LIFECYCLE = ["draft", "pending", "approved", "merged"] as const;

export function ProposalDetailPage({ proposalId }: { proposalId: string }) {
  const proposal = useProposal(proposalId);

  return (
    <div className="flex flex-col gap-6">
      <QueryState query={proposal}>
        {(data) => (
          <>
            <header className="flex flex-col gap-2">
              <h1 className="text-2xl font-semibold tracking-tight">{data.title}</h1>
              {data.description ? (
                <p className="text-muted-foreground">{data.description}</p>
              ) : null}
              <LifecycleStepper status={data.status} reviewNote={data.review_note} />
            </header>

            <DraftsCard drafts={data.drafts ?? []} />

            {/* Two physically separate cards, two different verbs, two
                different colors — approval and merge must never be
                reachable from the same control (M7b's explicit rule). */}
            <ReviewCard proposalId={proposalId} status={data.status} />
            <MergeCard
              proposalId={proposalId}
              status={data.status}
              mergedEventIds={data.merged_event_ids ?? []}
            />
            <UndoCard proposalId={proposalId} status={data.status} />

            <TimelineCard proposalId={proposalId} />
          </>
        )}
      </QueryState>
    </div>
  );
}

function LifecycleStepper({
  status,
  reviewNote,
}: {
  status: string;
  reviewNote: string | null | undefined;
}) {
  if (status === "rejected") {
    return (
      <div className="flex items-center gap-2">
        <Badge variant="destructive">rejected</Badge>
        {reviewNote ? <span className="text-sm text-muted-foreground">"{reviewNote}"</span> : null}
      </div>
    );
  }
  if (status === "undone") {
    return <Badge variant="outline">undone — compensated, not erased</Badge>;
  }

  const currentIndex = LIFECYCLE.indexOf(status as (typeof LIFECYCLE)[number]);
  return (
    <ol className="flex items-center gap-1 text-sm" aria-label="Proposal lifecycle">
      {LIFECYCLE.map((step, index) => (
        <li key={step} className="flex items-center gap-1">
          <span
            aria-current={index === currentIndex ? "step" : undefined}
            className={`rounded-full px-2.5 py-0.5 capitalize ${
              index === currentIndex
                ? "bg-primary font-medium text-primary-foreground"
                : index < currentIndex
                  ? "bg-emerald-600/15 text-emerald-700 dark:text-emerald-400"
                  : "bg-muted text-muted-foreground"
            }`}
          >
            {step}
          </span>
          {index < LIFECYCLE.length - 1 ? <span className="text-muted-foreground">→</span> : null}
        </li>
      ))}
    </ol>
  );
}

function DraftsCard({ drafts }: { drafts: Record<string, unknown>[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Draft intents</CardTitle>
        <CardDescription>What this proposal wants to append — not yet events.</CardDescription>
      </CardHeader>
      <CardContent>
        {drafts.length === 0 ? (
          <p className="text-sm text-muted-foreground">No drafts.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {drafts.map((draft) => {
              const memoryId = draftTargetId(draft);
              return (
                <li
                  key={JSON.stringify(draft)}
                  className="rounded-md border border-border p-2 text-sm"
                >
                  <div className="flex items-center gap-2">
                    <Badge variant="outline">{String(draft.op ?? "unknown")}</Badge>
                    {memoryId ? (
                      <Link
                        href={`/memories/${memoryId}`}
                        className="font-mono text-xs hover:underline"
                      >
                        {memoryId}
                      </Link>
                    ) : null}
                  </div>
                  <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-xs">
                    {Object.entries(draft)
                      .filter(([key]) => !["op", "draft_schema_version"].includes(key))
                      .map(([key, value]) => (
                        <div key={key} className="contents">
                          <dt className="text-muted-foreground">{key}</dt>
                          <dd className="break-words">
                            {typeof value === "object" ? JSON.stringify(value) : String(value)}
                          </dd>
                        </div>
                      ))}
                  </dl>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function ReviewCard({ proposalId, status }: { proposalId: string; status: string }) {
  const approve = useApproveProposal();
  const reject = useRejectProposal();
  const [note, setNote] = useState("");
  const reviewable = status === "pending";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">Review</CardTitle>
        <CardDescription>
          Approve or reject. Approving does <strong>not</strong> write any events — it only marks
          the proposal ready to merge.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Review note (optional)"
          rows={2}
          disabled={!reviewable}
          className="w-full rounded-md border border-input bg-background px-2 py-1 text-sm disabled:opacity-50"
        />
        <div className="flex gap-2">
          <Button
            variant="outline"
            disabled={!reviewable || approve.isPending}
            onClick={() => approve.mutate({ proposalId, note: note.trim() || undefined })}
          >
            <CheckCircle2 className="h-4 w-4 text-emerald-600" /> Approve
          </Button>
          <Button
            variant="outline"
            disabled={!reviewable || reject.isPending}
            onClick={() => reject.mutate({ proposalId, note: note.trim() || undefined })}
          >
            <XCircle className="h-4 w-4 text-destructive" /> Reject
          </Button>
        </div>
        {!reviewable ? (
          <p className="text-xs text-muted-foreground">
            Only pending proposals can be reviewed (current: {status}).
          </p>
        ) : null}
        {approve.isError ? <ErrorState error={approve.error} /> : null}
        {reject.isError ? <ErrorState error={reject.error} /> : null}
      </CardContent>
    </Card>
  );
}

function MergeCard({
  proposalId,
  status,
  mergedEventIds,
}: {
  proposalId: string;
  status: string;
  mergedEventIds: string[];
}) {
  const merge = useMergeProposal();
  const [confirming, setConfirming] = useState(false);
  const mergeable = status === "approved";

  return (
    <Card className="border-2 border-primary/30">
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <GitMerge aria-hidden="true" className="h-4 w-4" />
          Merge
        </CardTitle>
        <CardDescription>
          A separate, deliberate step. This is the <strong>only</strong> action that appends events
          to the log — disabled until the proposal is approved.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {status === "merged" ? (
          <p className="text-sm text-emerald-600 dark:text-emerald-400">
            Merged — {mergedEventIds.length} event{mergedEventIds.length === 1 ? "" : "s"} appended.
          </p>
        ) : confirming ? (
          <div className="flex items-center gap-2">
            <Button
              variant="default"
              disabled={merge.isPending}
              onClick={() =>
                merge.mutate({ proposalId }, { onSettled: () => setConfirming(false) })
              }
            >
              Confirm merge — write events now
            </Button>
            <Button variant="ghost" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </div>
        ) : (
          <Button variant="default" disabled={!mergeable} onClick={() => setConfirming(true)}>
            Merge proposal
          </Button>
        )}
        {!mergeable && status !== "merged" ? (
          <p className="text-xs text-muted-foreground">
            Approve this proposal first (current: {status}).
          </p>
        ) : null}
        {merge.isError ? <ErrorState error={merge.error} /> : null}
      </CardContent>
    </Card>
  );
}

function UndoCard({ proposalId, status }: { proposalId: string; status: string }) {
  const undo = useUndoProposal();
  const [confirming, setConfirming] = useState(false);
  const undoable = status === "merged";

  if (!undoable && status !== "undone") return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <Undo2 aria-hidden="true" className="h-4 w-4" />
          Undo
        </CardTitle>
        <CardDescription>
          Compensates every event this merge appended, in reverse (ADR-0018 §3).
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {status === "undone" ? (
          <p className="text-sm text-muted-foreground">Already undone.</p>
        ) : confirming ? (
          <div className="flex items-center gap-2">
            <Button
              variant="destructive"
              disabled={undo.isPending}
              onClick={() => undo.mutate({ proposalId }, { onSettled: () => setConfirming(false) })}
            >
              Confirm undo
            </Button>
            <Button variant="ghost" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </div>
        ) : (
          <Button variant="outline" onClick={() => setConfirming(true)}>
            Undo merge
          </Button>
        )}
        {undo.isError ? <ErrorState error={undo.error} /> : null}
      </CardContent>
    </Card>
  );
}

function TimelineCard({ proposalId }: { proposalId: string }) {
  const timeline = useProposalTimeline(proposalId);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <History aria-hidden="true" className="h-4 w-4" />
          Lifecycle history &amp; provenance
        </CardTitle>
      </CardHeader>
      <CardContent>
        <QueryState
          query={timeline}
          isEmpty={(data) => data.entries.length === 0}
          empty={<p className="text-sm text-muted-foreground">No history.</p>}
        >
          {(data) => (
            <ol className="flex flex-col gap-3">
              {data.entries.map((entry) => (
                <li key={entry.event_id} className="rounded-md border border-border p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-sm font-medium">{entry.event_type}</span>
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
  );
}
