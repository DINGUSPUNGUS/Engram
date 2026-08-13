"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { type ProposalListFilters, queryKeys } from "@/lib/api/keys";

/**
 * Proposal Review's data layer. Approve, reject, merge, and undo are four
 * separate calls to four separate endpoints — nothing here ever combines
 * approve+merge into one action, which is the whole point of ADR-0018's
 * two-step review (see ProposalActions in features/proposals).
 */

export function useProposals(filters: ProposalListFilters = {}) {
  return useQuery({
    queryKey: queryKeys.proposals(filters),
    queryFn: async () => {
      const result = await apiClient.GET("/api/v1/proposals", {
        params: { query: { status: filters.status, cursor: filters.cursor } },
      });
      return unwrap(result);
    },
  });
}

export function useProposal(proposalId: string | undefined) {
  const id = proposalId ?? "";
  return useQuery({
    queryKey: queryKeys.proposal(id),
    // `enabled` gates whether this ever runs — an empty id here never
    // reaches the network, so a fallback is safe and avoids `proposalId!`.
    queryFn: async () => {
      const result = await apiClient.GET("/api/v1/proposals/{proposal_id}", {
        params: { path: { proposal_id: id } },
      });
      return unwrap(result);
    },
    enabled: proposalId !== undefined,
  });
}

export function useProposalTimeline(proposalId: string | undefined) {
  const id = proposalId ?? "";
  return useQuery({
    queryKey: queryKeys.proposalTimeline(id),
    queryFn: async () => {
      const result = await apiClient.GET("/api/v1/proposals/{proposal_id}/timeline", {
        params: { path: { proposal_id: id } },
      });
      return unwrap(result);
    },
    enabled: proposalId !== undefined,
  });
}

function useProposalMutation<TArgs extends { proposalId: string }, TData>(
  mutationFn: (args: TArgs) => Promise<TData>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.proposal(variables.proposalId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.proposals() });
      // A merge appends memory events too; the SSE stream will invalidate
      // the specific memories affected, but the list/search families are
      // cheap enough to refresh eagerly here rather than wait for a push.
      void queryClient.invalidateQueries({ queryKey: queryKeys.memories() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.stats() });
    },
  });
}

/** Approve an open proposal. Does not merge — a separate, explicit step. */
export function useApproveProposal() {
  return useProposalMutation(
    async ({ proposalId, note }: { proposalId: string; note?: string }) => {
      const result = await apiClient.POST("/api/v1/proposals/{proposal_id}/approve", {
        params: { path: { proposal_id: proposalId } },
        body: { note: note ?? null },
      });
      return unwrap(result);
    },
  );
}

/** Reject an open proposal. Its drafts never become events. */
export function useRejectProposal() {
  return useProposalMutation(
    async ({ proposalId, note }: { proposalId: string; note?: string }) => {
      const result = await apiClient.POST("/api/v1/proposals/{proposal_id}/reject", {
        params: { path: { proposal_id: proposalId } },
        body: { note: note ?? null },
      });
      return unwrap(result);
    },
  );
}

/** Execute an approved proposal — the only step that appends memory events. */
export function useMergeProposal() {
  return useProposalMutation(async ({ proposalId }: { proposalId: string }) => {
    const result = await apiClient.POST("/api/v1/proposals/{proposal_id}/merge", {
      params: { path: { proposal_id: proposalId } },
    });
    return unwrap(result);
  });
}

/** Compensate a merged proposal (ADR-0018 §3): inverse events, never erasure. */
export function useUndoProposal() {
  return useProposalMutation(
    async ({ proposalId, note }: { proposalId: string; note?: string }) => {
      const result = await apiClient.POST("/api/v1/proposals/{proposal_id}/undo", {
        params: { path: { proposal_id: proposalId } },
        body: { note: note ?? null },
      });
      return unwrap(result);
    },
  );
}
