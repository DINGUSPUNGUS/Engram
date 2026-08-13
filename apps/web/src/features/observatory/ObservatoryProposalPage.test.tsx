import { screen, within } from "@testing-library/react";
import { expect, test } from "vitest";

import { ObservatoryProposalPage } from "@/features/observatory/ObservatoryProposalPage";
import { db, seedProposal } from "@/test/msw/state";
import { renderWithClient } from "@/test/render";

test("renders the pipeline explanation parsed from ProposalOpened's provenance detail", async () => {
  const proposal = seedProposal();

  renderWithClient(<ObservatoryProposalPage proposalId={proposal.id} />);
  await screen.findByRole("heading", { name: proposal.title });

  const explanationHeading = screen.getByText("Why this was proposed");
  const explanationCard = explanationHeading.closest("div")?.parentElement;
  expect(explanationCard).not.toBeNull();
  expect(within(explanationCard as HTMLElement).getByText("fake")).toBeDefined(); // provider
  expect(within(explanationCard as HTMLElement).getByText("fake-model")).toBeDefined(); // model
});

test("degrades honestly when there is no pipeline provenance to show", async () => {
  const proposal = seedProposal({ id: crypto.randomUUID() });
  // Overwrite this proposal's timeline with a detail-less ProposalOpened —
  // simulating a hand-written CLI event, per ADR-0022 §4.
  const entries = db.proposalTimelines.get(proposal.id);
  if (entries?.[0]) entries[0].provenance.detail = null;

  renderWithClient(<ObservatoryProposalPage proposalId={proposal.id} />);
  await screen.findByRole("heading", { name: proposal.title });

  // Shown both in "Why this was proposed" and in the full lifecycle
  // listing — both are honest, neither fabricates a provider/model.
  await screen.findAllByText("no pipeline provenance recorded");
  expect(screen.getAllByText("no pipeline provenance recorded").length).toBeGreaterThan(0);
});
