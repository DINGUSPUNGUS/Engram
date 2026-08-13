import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";

import { TimelinePage } from "@/features/timeline/TimelinePage";
import { seedMemory } from "@/test/msw/state";
import { renderWithClient } from "@/test/render";

test("renders the chronological event stream and links to the owning memory", async () => {
  const memory = seedMemory({ title: "Prefers dark mode" });

  renderWithClient(<TimelinePage />);

  expect(await screen.findByText("MemoryCreated")).toBeDefined();
  await userEvent.click(screen.getByRole("button", { name: /toggle details/i }));

  const link = await screen.findByRole("link", { name: /view memory/i });
  expect(link.getAttribute("href")).toBe(`/memories/${memory.id}`);
});

test("expanding a row fetches full provenance from the owning stream", async () => {
  seedMemory({ title: "Prefers dark mode" });

  renderWithClient(<TimelinePage />);
  await screen.findByText("MemoryCreated");
  await userEvent.click(screen.getByRole("button", { name: /toggle details/i }));

  expect(await screen.findByText("actor")).toBeDefined();
  expect(screen.getByText("test-fixture")).toBeDefined();
});
