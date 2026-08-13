import type { components } from "@engram/api-client";

type Problem = components["schemas"]["Problem"];

/**
 * Every non-2xx response from the engram API is RFC 9457
 * `application/problem+json` (apps/api/src/engram_api/errors.py). This is the
 * one place that shape becomes a JS error, so every feature handles failure
 * the same way instead of re-parsing response bodies.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly title: string;
  readonly detail?: string;
  readonly instance?: string;

  constructor(problem: Partial<Problem>, fallbackStatus: number) {
    super(problem.detail ?? problem.title ?? `Request failed (${fallbackStatus})`);
    this.name = "ApiError";
    this.status = problem.status ?? fallbackStatus;
    this.title = problem.title ?? "Request failed";
    this.detail = problem.detail ?? undefined;
    this.instance = problem.instance ?? undefined;
  }
}

/** Shape every `openapi-fetch` call resolves to. */
interface FetchResult<T> {
  data?: T;
  error?: Problem;
  response: Response;
}

/**
 * Unwraps an `openapi-fetch` result: returns the typed body on success, throws
 * `ApiError` on failure. Every hook in `lib/api/hooks` routes through this so
 * TanStack Query's error state is always an `ApiError`, never a raw Response.
 */
export function unwrap<T>(result: FetchResult<T>): T {
  if (result.error) {
    throw new ApiError(result.error, result.response.status);
  }
  if (result.data === undefined) {
    throw new ApiError(
      { title: "Empty response", status: result.response.status },
      result.response.status,
    );
  }
  return result.data;
}

/** Same as {@link unwrap}, for endpoints that legitimately return no body (204). */
export function unwrapVoid(result: Omit<FetchResult<unknown>, "data">): void {
  if (result.error) {
    throw new ApiError(result.error, result.response.status);
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}
