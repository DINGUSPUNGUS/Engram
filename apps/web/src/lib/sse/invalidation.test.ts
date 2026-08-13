import { expect, test } from "vitest";

import { invalidationKeysFor } from "@/lib/sse/invalidation";

test("a Memory* event invalidates that memory, the memory list, search, stats, and events", () => {
  const keys = invalidationKeysFor({ event_type: "MemoryEdited", stream_id: "mem-1" });

  expect(keys).toContainEqual(["memory", "mem-1"]);
  expect(keys).toContainEqual(["memories", {}]);
  expect(keys).toContainEqual(["search"]);
  expect(keys).toContainEqual(["stats"]);
});

test("a Proposal* event invalidates that proposal and the proposal list, not memories", () => {
  const keys = invalidationKeysFor({ event_type: "ProposalApproved", stream_id: "prop-1" });

  expect(keys).toContainEqual(["proposal", "prop-1"]);
  expect(keys).toContainEqual(["proposals", {}]);
  expect(keys.some((k) => JSON.stringify(k).includes("mem-1"))).toBe(false);
});

test("an unrecognized event type still invalidates the shared stats/events keys", () => {
  const keys = invalidationKeysFor({ event_type: "SomethingElse", stream_id: "x" });

  expect(keys).toContainEqual(["stats"]);
  expect(keys).toContainEqual(["events", 0]);
});
