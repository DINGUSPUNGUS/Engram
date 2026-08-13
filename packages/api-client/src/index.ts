/**
 * engram API client.
 *
 * The OpenAPI schema exported from apps/api is the contract; `pnpm gen:client`
 * regenerates `src/generated/schema.d.ts` from it, and CI fails when the two
 * drift. Never edit generated files by hand.
 */
import createClient from "openapi-fetch";

import type { paths } from "./generated/schema";

export interface EngramClientOptions {
  /** Origin of the engram API, e.g. `http://127.0.0.1:8000`. */
  baseUrl?: string;
  /** Identifies the calling assistant/tool in event provenance. */
  actor?: string;
}

export const DEFAULT_BASE_URL = "http://127.0.0.1:8000";

export function createEngramClient(options: EngramClientOptions = {}) {
  return createClient<paths>({
    baseUrl: options.baseUrl ?? DEFAULT_BASE_URL,
    headers: options.actor ? { "X-Engram-Actor": options.actor } : undefined,
  });
}

export type EngramClient = ReturnType<typeof createEngramClient>;
export type { components, paths } from "./generated/schema";
