import { createEngramClient, DEFAULT_BASE_URL } from "@engram/api-client";

/**
 * The single API client instance for the dashboard. All data access goes
 * through @engram/api-client so the wire contract stays typed end to end.
 */
export const apiClient = createEngramClient({
  baseUrl: process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_BASE_URL,
  actor: "web-dashboard",
});
