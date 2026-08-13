import { createEngramClient, DEFAULT_BASE_URL } from "@engram/api-client";

/** Resolved once so the SSE provider (a plain `EventSource`, outside
 * `@engram/api-client`) hits the exact same origin as every typed call. */
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_BASE_URL;

/**
 * The single API client instance for the dashboard. All data access goes
 * through @engram/api-client so the wire contract stays typed end to end.
 */
export const apiClient = createEngramClient({
  baseUrl: API_BASE_URL,
  actor: "web-dashboard",
});
