import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";

import { ConsolePage } from "@/features/console/ConsolePage";
import { seedMemory } from "@/test/msw/state";
import { renderWithClient } from "@/test/render";

test("stats & rebuild: shows current stats and replays the log on confirm", async () => {
  seedMemory();

  renderWithClient(<ConsolePage />);
  await userEvent.click(screen.getByRole("tab", { name: "Stats & rebuild" }));

  expect(await screen.findByText(/"memory_count": 1/)).toBeDefined();

  await userEvent.click(screen.getByRole("button", { name: "Rebuild projections" }));
  await userEvent.click(screen.getByRole("button", { name: "Confirm rebuild" }));

  expect(await screen.findByText(/replayed 1 events/)).toBeDefined();
});

test("search tab surfaces a malformed query as a 422 problem, not a silent failure", async () => {
  renderWithClient(<ConsolePage />);

  await userEvent.type(screen.getByPlaceholderText("engram query language"), "confidence>>0.8");
  await userEvent.click(screen.getByRole("button", { name: "Run" }));

  expect(await screen.findByText("Validation failed")).toBeDefined();
});
