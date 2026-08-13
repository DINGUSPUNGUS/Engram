import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";

import { ProposalDetailPage } from "@/features/proposals/ProposalDetailPage";
import { seedProposal } from "@/test/msw/state";
import { renderWithClient } from "@/test/render";

test("merge is disabled until the proposal is approved — no route can bypass review", async () => {
  const proposal = seedProposal({ status: "pending" });

  renderWithClient(<ProposalDetailPage proposalId={proposal.id} />);
  await screen.findByRole("heading", { name: proposal.title });

  const mergeButton = screen.getByRole("button", { name: "Merge proposal" });
  expect(mergeButton).toHaveProperty("disabled", true);
  expect(screen.getByText(/Approve this proposal first/)).toBeDefined();
});

test("approve does not merge — it only unlocks the separate merge action", async () => {
  const proposal = seedProposal({ status: "pending" });

  renderWithClient(<ProposalDetailPage proposalId={proposal.id} />);
  await screen.findByRole("heading", { name: proposal.title });

  await userEvent.click(screen.getByRole("button", { name: "Approve" }));

  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Merge proposal" })).not.toHaveProperty(
      "disabled",
      true,
    ),
  );
  // Still no memory appended — approval alone never writes events.
  expect(screen.queryByText(/event.*appended/)).toBeNull();
});

test("reject: an open proposal's drafts never become events", async () => {
  const proposal = seedProposal({ status: "pending" });

  renderWithClient(<ProposalDetailPage proposalId={proposal.id} />);
  await screen.findByRole("heading", { name: proposal.title });

  await userEvent.click(screen.getByRole("button", { name: "Reject" }));

  expect(await screen.findByText("rejected")).toBeDefined();
});

test("merge: the confirmed, explicit action appends events and shows the count", async () => {
  const proposal = seedProposal({ status: "approved" });

  renderWithClient(<ProposalDetailPage proposalId={proposal.id} />);
  await screen.findByRole("heading", { name: proposal.title });

  await userEvent.click(screen.getByRole("button", { name: "Merge proposal" }));
  await userEvent.click(screen.getByRole("button", { name: "Confirm merge — write events now" }));

  expect(await screen.findByText(/1 event appended/)).toBeDefined();
});

test("undo: compensates a merged proposal's events, offered only after merge", async () => {
  const proposal = seedProposal({ status: "merged", merged_event_ids: ["evt-1"] });

  renderWithClient(<ProposalDetailPage proposalId={proposal.id} />);
  await screen.findByRole("heading", { name: proposal.title });

  await userEvent.click(screen.getByRole("button", { name: "Undo merge" }));
  await userEvent.click(screen.getByRole("button", { name: "Confirm undo" }));

  await waitFor(() => expect(screen.getByText("Already undone.")).toBeDefined());
});
