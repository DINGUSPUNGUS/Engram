"use client";

import { Telescope } from "lucide-react";
import Link from "next/link";

import { ErrorState, LoadingState } from "@/components/status";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useMemories } from "@/lib/api/hooks/memories";
import { useProposals } from "@/lib/api/hooks/proposals";

/**
 * Observatory landing: pick a memory or a proposal to explain. Everything
 * it can say is reconstructed from the event log (ADR-0022) — there is no
 * separate "explanation" store, so this page is just a jumping-off point
 * into the same timeline/provenance reads Memory Explorer and Proposal
 * Review already use.
 */
export function ObservatoryPage() {
  const memories = useMemories();
  const proposals = useProposals({ status: undefined });

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <Telescope aria-hidden="true" className="h-6 w-6" />
          Observatory
        </h1>
        <p className="text-muted-foreground">
          Reconstructs "why does this exist?" from evented facts only — never a guess (ADR-0022).
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Memories</CardTitle>
            <CardDescription>Pick a memory to see its provenance and origin.</CardDescription>
          </CardHeader>
          <CardContent>
            {memories.isPending ? <LoadingState /> : null}
            {memories.isError ? (
              <ErrorState error={memories.error} onRetry={memories.refetch} />
            ) : null}
            {memories.data ? (
              <ul className="flex flex-col divide-y divide-border">
                {memories.data.items.slice(0, 10).map((memory) => (
                  <li key={memory.id} className="py-1.5">
                    <Link
                      href={`/observatory/memories/${memory.id}`}
                      className="text-sm hover:underline"
                    >
                      {memory.title}
                    </Link>
                  </li>
                ))}
                {memories.data.items.length === 0 ? (
                  <p className="py-2 text-sm text-muted-foreground">No memories yet.</p>
                ) : null}
              </ul>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Proposals</CardTitle>
            <CardDescription>
              Pick a proposal to see its pipeline explanation, if any.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {proposals.isPending ? <LoadingState /> : null}
            {proposals.isError ? (
              <ErrorState error={proposals.error} onRetry={proposals.refetch} />
            ) : null}
            {proposals.data ? (
              <ul className="flex flex-col divide-y divide-border">
                {proposals.data.items.slice(0, 10).map((proposal) => (
                  <li key={proposal.id} className="py-1.5">
                    <Link
                      href={`/observatory/proposals/${proposal.id}`}
                      className="text-sm hover:underline"
                    >
                      {proposal.title}
                    </Link>
                  </li>
                ))}
                {proposals.data.items.length === 0 ? (
                  <p className="py-2 text-sm text-muted-foreground">No proposals yet.</p>
                ) : null}
              </ul>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
