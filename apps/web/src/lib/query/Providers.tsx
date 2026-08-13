"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";

import { createQueryClient } from "@/lib/api/queryClient";
import { EventStreamProvider } from "@/lib/sse/EventStreamProvider";

/** Root client boundary: one `QueryClient` per browser session (not per
 * render — `useState`'s initializer runs once) and the one shared SSE
 * connection every view invalidates through. */
export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(createQueryClient);

  return (
    <QueryClientProvider client={queryClient}>
      <EventStreamProvider>{children}</EventStreamProvider>
    </QueryClientProvider>
  );
}
