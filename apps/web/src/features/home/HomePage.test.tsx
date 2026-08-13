import { screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { expect, test } from "vitest";

import { HomePage } from "@/features/home/HomePage";
import { server } from "@/test/msw/server";
import { renderWithClient } from "@/test/render";

test("loads from a fresh space: zero counts, no drift, empty activity", async () => {
  renderWithClient(<HomePage />);

  await waitFor(() => expect(screen.getAllByText("0").length).toBeGreaterThanOrEqual(3));
  expect(screen.getByText("Up to date")).toBeDefined();
  expect(await screen.findByText("No events yet — this space is empty.")).toBeDefined();
});

test("renders RFC 9457 errors with a retry action", async () => {
  server.use(
    http.get("*/api/v1/stats", () =>
      HttpResponse.json(
        { type: "about:blank", title: "Storage failure", status: 500, detail: "disk is on fire" },
        { status: 500, headers: { "Content-Type": "application/problem+json" } },
      ),
    ),
  );

  renderWithClient(<HomePage />);

  expect((await screen.findAllByText("Storage failure")).length).toBeGreaterThan(0);
  expect(screen.getAllByText("disk is on fire").length).toBeGreaterThan(0);
  expect(screen.getAllByRole("button", { name: /retry/i }).length).toBeGreaterThan(0);
});
