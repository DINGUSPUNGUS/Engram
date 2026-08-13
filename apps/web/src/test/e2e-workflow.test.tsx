import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";

import { HomePage } from "@/features/home/HomePage";
import { MemoryListPage } from "@/features/memory-explorer/MemoryListPage";
import { ProposalDetailPage } from "@/features/proposals/ProposalDetailPage";
import { ProposalListPage } from "@/features/proposals/ProposalListPage";
import { TimelinePage } from "@/features/timeline/TimelinePage";
import { apiClient } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { createMemoryDraft, db } from "@/test/msw/state";

/**
 * End-to-end: assistant-generated proposal → dashboard review → approve →
 * merge → memory appears → timeline updates → undo → memory reverts →
 * rebuild → dashboard stays consistent. Every step renders the real page
 * component against the real hooks and the mock HTTP layer — nothing here
 * touches `db` to shortcut a step except reading it back to assert.
 *
 * A shared `QueryClient` stands in for React Router/Next's persistence of
 * cache across navigations; each "screen" is a fresh `render()` of that
 * step's page component, which is how a client-side navigation behaves.
 */
test("assistant proposal → review → merge → memory → timeline → undo → rebuild stays consistent", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const renderScreen = (ui: React.ReactElement) =>
    render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);

  // 1. An assistant submits a proposal over the real HTTP surface.
  const opened = unwrap(
    await apiClient.POST("/api/v1/proposals", {
      body: {
        title: "Remember dark mode preference",
        description: "extracted from chat",
        proposed_events: [createMemoryDraft({ title: "Prefers dark mode" })],
      },
    }),
  );
  expect(opened.status).toBe("pending");

  // 2. It shows up in the dashboard's review queue.
  const { unmount: unmountQueue } = renderScreen(<ProposalListPage />);
  expect(await screen.findByText("Remember dark mode preference")).toBeDefined();
  unmountQueue();

  // 3. Approve, then merge — two separate, explicit actions.
  const { unmount: unmountDetail } = renderScreen(<ProposalDetailPage proposalId={opened.id} />);
  await screen.findByRole("heading", { name: "Remember dark mode preference" });
  await userEvent.click(screen.getByRole("button", { name: "Approve" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Merge proposal" })).not.toHaveProperty(
      "disabled",
      true,
    ),
  );
  await userEvent.click(screen.getByRole("button", { name: "Merge proposal" }));
  await userEvent.click(screen.getByRole("button", { name: "Confirm merge — write events now" }));
  expect(await screen.findByText(/1 event appended/)).toBeDefined();
  unmountDetail();

  // 4. The memory now exists and appears in Memory Explorer.
  const { unmount: unmountList } = renderScreen(<MemoryListPage />);
  expect(await screen.findByText("Prefers dark mode")).toBeDefined();
  unmountList();

  const [memory] = db.memories.values();
  expect(memory).toBeDefined();

  // 5. The timeline reflects the whole causal chain, in order.
  const { unmount: unmountTimeline } = renderScreen(<TimelinePage />);
  await screen.findByText("ProposalOpened");
  const rows = screen.getAllByRole("listitem");
  const order = rows.map((row) => within(row).queryByText(/^(Proposal|Memory)\w+$/)?.textContent);
  expect(order).toEqual(["ProposalOpened", "ProposalApproved", "MemoryCreated", "ProposalMerged"]);
  unmountTimeline();

  // 6. Undo the merge — the memory it created reverts (compensated, not
  // silently erased: the proposal moves to "undone", not back to "merged").
  const { unmount: unmountUndo } = renderScreen(<ProposalDetailPage proposalId={opened.id} />);
  await screen.findByRole("heading", { name: "Remember dark mode preference" });
  await userEvent.click(screen.getByRole("button", { name: "Undo merge" }));
  await userEvent.click(screen.getByRole("button", { name: "Confirm undo" }));
  await waitFor(() => expect(screen.getByText("Already undone.")).toBeDefined());
  unmountUndo();
  expect(db.memories.size).toBe(0);

  // 7. Rebuild, then confirm Home still renders a consistent, correct
  // picture — the disposability invariant, from the dashboard's own view.
  await unwrap(await apiClient.POST("/admin/rebuild", {}));
  const { unmount: unmountHome } = renderScreen(<HomePage />);
  await waitFor(() => expect(screen.getAllByText("0").length).toBeGreaterThan(0)); // memory_count back to 0
  expect(screen.getByText("1")).toBeDefined(); // proposal_count: still exists, just undone
  unmountHome();
}, 20_000);
