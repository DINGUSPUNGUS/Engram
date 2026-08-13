import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";

import { MemoryDetailPage } from "@/features/memory-explorer/MemoryDetailPage";
import { appendEvent, appendTimelineEntry, db, seedMemory, snapshotMemory } from "@/test/msw/state";
import { renderWithClient } from "@/test/render";

test("memory inspection: title, spine, evidence, and event history render", async () => {
  const memory = seedMemory({
    title: "Prefers dark mode",
    content: "User said they prefer dark mode.",
    confidence: 0.8,
    evidence: [
      { evidence_type: "quote", value: '"I like dark mode"', note: null, actor: "claude" },
    ],
  });

  renderWithClient(<MemoryDetailPage memoryId={memory.id} />);

  expect(await screen.findByRole("heading", { name: "Prefers dark mode" })).toBeDefined();
  // Confidence and effective confidence are both 80% by default — two
  // legitimate matches, not a duplicate render.
  expect(screen.getAllByText("80%").length).toBe(2);
  expect(screen.getByText('"I like dark mode"')).toBeDefined();

  const timelineCard = screen.getByText("Event history & provenance").closest("div")?.parentElement;
  expect(timelineCard).not.toBeNull();
  // The timeline is a separate, independently-loading query — give it time
  // to resolve rather than asserting against the pre-fetch DOM.
  expect(await within(timelineCard as HTMLElement).findByText("MemoryCreated")).toBeDefined();
});

test("time travel reconstructs an earlier version", async () => {
  const memory = seedMemory({ title: "v1 title" });
  const v2 = { ...memory, title: "v2 title", version: 2 };
  db.memories.set(memory.id, v2);
  snapshotMemory(v2);
  const event = appendEvent(memory.id, "MemoryEdited", "user");
  appendTimelineEntry(db.memoryTimelines, memory.id, event);

  renderWithClient(<MemoryDetailPage memoryId={memory.id} />);
  await screen.findByRole("heading", { name: "v2 title" });

  const versionInput = screen.getByRole("spinbutton");
  await userEvent.clear(versionInput);
  await userEvent.type(versionInput, "1");
  await userEvent.click(screen.getByRole("button", { name: "Reconstruct" }));

  expect(await screen.findByText("v1 title", { selector: "p" })).toBeDefined();
});

test("undo compensates the last change", async () => {
  const memory = seedMemory({ title: "v1 title" });
  const v2 = { ...memory, title: "v2 title", version: 2 };
  db.memories.set(memory.id, v2);
  snapshotMemory(v2);
  const editEvent = appendEvent(memory.id, "MemoryEdited", "user");
  appendTimelineEntry(db.memoryTimelines, memory.id, editEvent);

  renderWithClient(<MemoryDetailPage memoryId={memory.id} />);
  await screen.findByRole("heading", { name: "v2 title" });

  await userEvent.click(screen.getByRole("button", { name: "Undo last change" }));
  await userEvent.click(screen.getByRole("button", { name: "Confirm undo" }));

  await waitFor(() => expect(screen.getByText(/Reverted\./)).toBeDefined());
  expect(await screen.findByRole("heading", { name: "v1 title" })).toBeDefined();
});

test("undo with no compensator is refused as a 409, not silently ignored", async () => {
  const memory = seedMemory({ title: "only version" });

  renderWithClient(<MemoryDetailPage memoryId={memory.id} />);
  await screen.findByRole("heading", { name: "only version" });

  await userEvent.click(screen.getByRole("button", { name: "Undo last change" }));
  await userEvent.click(screen.getByRole("button", { name: "Confirm undo" }));

  expect(await screen.findByText("no compensator exists for this event type")).toBeDefined();
});
