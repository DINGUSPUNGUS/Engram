import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";

import { MemoryListPage } from "@/features/memory-explorer/MemoryListPage";
import { seedMemory } from "@/test/msw/state";
import { renderWithClient } from "@/test/render";

test("lists existing memories", async () => {
  seedMemory({ title: "Prefers dark mode", kind: "preference" });

  renderWithClient(<MemoryListPage />);

  expect(await screen.findByText("Prefers dark mode")).toBeDefined();
});

test("shows an empty state for a fresh space", async () => {
  renderWithClient(<MemoryListPage />);

  expect(await screen.findByText("No memories yet")).toBeDefined();
});

test("search runs the query language against /search, not a client-side filter", async () => {
  seedMemory({ title: "Prefers dark mode", content: "user likes dark ui" });
  seedMemory({ title: "Works at Acme", content: "employment fact" });

  renderWithClient(<MemoryListPage />);
  await userEvent.type(screen.getByPlaceholderText(/kind:project/i), "dark mode");

  await waitFor(() => expect(screen.getByText("Prefers dark mode")).toBeDefined());
  expect(screen.queryByText("Works at Acme")).toBeNull();
});
