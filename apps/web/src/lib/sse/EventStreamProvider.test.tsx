import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { EventStreamProvider, useEventStreamStatus } from "@/lib/sse/EventStreamProvider";

/** jsdom has no `EventSource`; this stands in for the browser's real one so
 * `EventStreamProvider`'s message/error/reconnect handling can be driven
 * from a test without a real HTTP connection. */
class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  closeSpy = vi.fn();
  private listeners = new Map<string, ((event: { data: string }) => void)[]>();

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, callback: (event: { data: string }) => void) {
    const list = this.listeners.get(type) ?? [];
    list.push(callback);
    this.listeners.set(type, list);
  }

  close() {
    this.closeSpy();
  }

  emitOpen() {
    this.onopen?.();
  }

  emitMessage(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }

  emitNamed(type: string) {
    for (const cb of this.listeners.get(type) ?? []) cb({ data: "{}" });
  }

  emitError() {
    this.onerror?.();
  }
}

function StatusProbe() {
  return <span data-testid="status">{useEventStreamStatus()}</span>;
}

beforeEach(() => {
  MockEventSource.instances = [];
  vi.stubGlobal("EventSource", MockEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("opens exactly one stream shared by every view, and reports status transitions", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <EventStreamProvider>
        <StatusProbe />
      </EventStreamProvider>
    </QueryClientProvider>,
  );

  expect(MockEventSource.instances).toHaveLength(1);
  expect(screen.getByTestId("status").textContent).toBe("connecting");

  MockEventSource.instances[0]?.emitOpen();
  await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("open"));
});

test("a pushed event invalidates the affected query, never folds into state", async () => {
  const client = new QueryClient();
  const invalidateSpy = vi.spyOn(client, "invalidateQueries");

  render(
    <QueryClientProvider client={client}>
      <EventStreamProvider>
        <StatusProbe />
      </EventStreamProvider>
    </QueryClientProvider>,
  );
  MockEventSource.instances[0]?.emitOpen();

  MockEventSource.instances[0]?.emitMessage({
    event_id: "e1",
    stream_id: "mem-1",
    event_type: "MemoryEdited",
    global_seq: 1,
    occurred_at: "2026-01-01T00:00:00Z",
    actor: "user",
  });

  await waitFor(() =>
    expect(invalidateSpy).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: ["memory", "mem-1"] }),
    ),
  );
});

test("a resync signal invalidates everything rather than serving partial history", async () => {
  const client = new QueryClient();
  const invalidateSpy = vi.spyOn(client, "invalidateQueries");

  render(
    <QueryClientProvider client={client}>
      <EventStreamProvider>
        <StatusProbe />
      </EventStreamProvider>
    </QueryClientProvider>,
  );

  MockEventSource.instances[0]?.emitNamed("resync");

  await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith());
});

test("reconnect is left entirely to the browser's own EventSource: an error never triggers a manual close/reopen", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <EventStreamProvider>
        <StatusProbe />
      </EventStreamProvider>
    </QueryClientProvider>,
  );
  const source = MockEventSource.instances[0];
  source?.emitOpen();
  await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("open"));

  source?.emitError();

  await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("reconnecting"));
  // The provider never closes the connection itself on error — the
  // browser's EventSource reconnects on its own (and resends
  // Last-Event-ID automatically), which this proves by absence.
  expect(source?.closeSpy).not.toHaveBeenCalled();
  expect(MockEventSource.instances).toHaveLength(1);
});
