import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";

/** Renders a component behind a fresh `QueryClient` per test — the same
 * boundary `Providers.tsx` gives the real app, minus the SSE connection
 * (jsdom has no `EventSource`; SSE has its own dedicated tests with a mock
 * one). Retries are off so failing-request tests resolve immediately. */
export function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return {
    client,
    ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>),
  };
}
