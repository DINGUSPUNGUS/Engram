import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

const SEARCH_WINDOW = 20;

/**
 * "Which proposal produced this memory event?" has no direct answer: merge
 * re-stamps appended memory events with the *merger's* provenance, not the
 * original proposer's (ADR-0019 §3's rich explanation lives only on
 * `ProposalOpened`), and no endpoint indexes event id → owning proposal.
 *
 * This is a genuine, named gap (ADR-0022 §3 predicts its sibling: "why was
 * this not created" is unanswerable for the same reason — the log doesn't
 * carry a mediating link). Rather than fabricate one or silently do an
 * unbounded search, this performs a small, explicit, user-triggered lookup
 * over the most recently merged proposals only, using nothing but existing
 * endpoints (`GET /proposals`, `GET /proposals/{id}`), and reports plainly
 * when it finds nothing within that window instead of implying there is
 * no origin.
 */
export function useFindOriginProposal() {
  return useMutation({
    mutationFn: async ({
      memoryEventIds,
    }: {
      memoryEventIds: string[];
    }): Promise<{ proposalId: string; proposalTitle: string } | null> => {
      const list = unwrap(
        await apiClient.GET("/api/v1/proposals", {
          params: { query: { status: "merged", limit: SEARCH_WINDOW } },
        }),
      );
      const eventIdSet = new Set(memoryEventIds);
      for (const summary of list.items) {
        const detail = unwrap(
          await apiClient.GET("/api/v1/proposals/{proposal_id}", {
            params: { path: { proposal_id: summary.id } },
          }),
        );
        if ((detail.merged_event_ids ?? []).some((id) => eventIdSet.has(id))) {
          return { proposalId: detail.id, proposalTitle: detail.title };
        }
      }
      return null;
    },
  });
}

export { SEARCH_WINDOW };
