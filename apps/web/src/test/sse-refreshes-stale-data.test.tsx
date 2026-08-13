import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { MemoryDetailPage } from "@/features/memory-explorer/MemoryDetailPage";
import { createQueryClient } from "@/lib/api/queryClient";
import { EventStreamProvider } from "@/lib/sse/EventStreamProvider";
import { db, seedMemory } from "@/test/msw/state";

/** The same fake used in EventStreamProvider's own unit tests — here it
 * drives a real feature page end to end, proving the full
 * "push → invalidate → refetch → render" loop the ADR-0023 flow promises,
 * not just that the right query key was named. */
class MockEventSource {
  static instances: MockEventSource[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  addEventListener() {}
  close() {}
  constructor() {
    MockEventSource.instances.push(this);
  }
  emitMessage(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

beforeEach(() => {
  MockEventSource.instances = [];
  vi.stubGlobal("EventSource", MockEventSource);
});
afterEach(() => vi.unstubAllGlobals());

test("a screen showing stale data refreshes to the authoritative state after an SSE invalidation — never from the pushed payload itself", async () => {
  const memory = seedMemory({ title: "Original title" });
  const client = createQueryClient();

  render(
    <QueryClientProvider client={client}>
      <EventStreamProvider>
        <MemoryDetailPage memoryId={memory.id} />
      </EventStreamProvider>
    </QueryClientProvider>,
  );
  await screen.findByRole("heading", { name: "Original title" });

  // Simulate a change made by another client (the CLI, an assistant) — the
  // mock server's state changes, exactly like a real concurrent writer.
  db.memories.set(memory.id, { ...memory, title: "Changed elsewhere" });

  // The push itself carries no payload (ADR-0023 §2) — only enough to say
  // "something changed here." The component must not — and structurally
  // cannot — render "Changed elsewhere" from this message directly.
  MockEventSource.instances[0]?.emitMessage({
    event_id: "e1",
    stream_id: memory.id,
    event_type: "MemoryEdited",
    global_seq: 1,
    occurred_at: "2026-01-01T00:00:00Z",
    actor: "cli",
  });

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Changed elsewhere" })).toBeDefined(),
  );
});
