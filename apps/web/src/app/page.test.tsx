import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import DashboardPage from "./page";

test("dashboard renders the project name and storage layers", () => {
  render(<DashboardPage />);
  expect(screen.getByRole("heading", { level: 1, name: "engram" })).toBeDefined();
  expect(screen.getByText("Event log")).toBeDefined();
  expect(screen.getByText("Markdown + git")).toBeDefined();
});
