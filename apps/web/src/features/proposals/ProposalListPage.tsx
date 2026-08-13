"use client";

import Link from "next/link";
import { useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { useProposals } from "@/lib/api/hooks/proposals";
import { formatRelativeTime } from "@/lib/format";

const STATUS_FILTERS = ["pending", "approved", "rejected", "merged", "undone", "all"] as const;

const STATUS_VARIANT: Record<
  string,
  "default" | "secondary" | "outline" | "success" | "warning" | "destructive"
> = {
  draft: "outline",
  pending: "warning",
  approved: "secondary",
  merged: "success",
  rejected: "destructive",
  undone: "outline",
};

/** Proposal Review's queue — pending proposals by default, any status on
 * request. Every row is exactly what `GET /api/v1/proposals` returns. */
export function ProposalListPage() {
  const [status, setStatus] = useState<(typeof STATUS_FILTERS)[number]>("pending");
  const proposals = useProposals({ status: status === "all" ? undefined : status });

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Proposal Review</h1>
        <p className="text-muted-foreground">
          Every memory change an assistant proposes waits here until a human approves and merges it.
        </p>
      </div>

      <div role="tablist" aria-label="Filter by status" className="flex flex-wrap gap-1.5">
        {STATUS_FILTERS.map((filter) => (
          <button
            key={filter}
            type="button"
            role="tab"
            aria-selected={status === filter}
            onClick={() => setStatus(filter)}
            className={`rounded-full border px-3 py-1 text-sm capitalize ${
              status === filter
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border text-muted-foreground hover:bg-accent"
            }`}
          >
            {filter}
          </button>
        ))}
      </div>

      {proposals.isPending ? <LoadingState /> : null}
      {proposals.isError ? (
        <ErrorState error={proposals.error} onRetry={proposals.refetch} />
      ) : null}
      {proposals.data && proposals.data.items.length === 0 ? (
        <EmptyState
          title={`No ${status === "all" ? "" : status} proposals`}
          description="Nothing waiting in this queue."
        />
      ) : null}
      {proposals.data && proposals.data.items.length > 0 ? (
        <ul className="flex flex-col divide-y divide-border rounded-lg border border-border">
          {proposals.data.items.map((proposal) => (
            <li key={proposal.id} className="flex items-center justify-between gap-3 p-3">
              <div className="flex flex-col gap-1">
                <Link href={`/proposals/${proposal.id}`} className="font-medium hover:underline">
                  {proposal.title}
                </Link>
                <p className="text-xs text-muted-foreground">
                  {proposal.draft_count} draft{proposal.draft_count === 1 ? "" : "s"} · opened by{" "}
                  {proposal.opened_by} · {formatRelativeTime(proposal.created_at)}
                </p>
              </div>
              <Badge variant={STATUS_VARIANT[proposal.status] ?? "outline"}>
                {proposal.status}
              </Badge>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
