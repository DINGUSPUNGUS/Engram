import { screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { SettingsPage } from "@/features/settings/SettingsPage";
import { renderWithClient } from "@/test/render";

test("renders the server's read-only configuration, with no mutation form", async () => {
  renderWithClient(<SettingsPage />);

  expect(await screen.findByText("/tmp/engram-test")).toBeDefined();
  expect(screen.getByText("proposal_submission")).toBeDefined();
  expect(screen.getByText("Initialized")).toBeDefined();
  expect(screen.getByText("yes")).toBeDefined();

  // Read-only: nothing on this screen submits a change.
  expect(screen.queryAllByRole("textbox")).toHaveLength(0);
  expect(screen.queryAllByRole("button", { name: /save|update|apply/i })).toHaveLength(0);
});
