import { expect, test } from "vitest";

import { ApiError, isApiError, unwrap, unwrapVoid } from "@/lib/api/errors";

test("unwrap returns the typed body on success", () => {
  const result = unwrap({ data: { ok: true }, response: new Response(null, { status: 200 }) });
  expect(result).toEqual({ ok: true });
});

test("unwrap throws an ApiError carrying the RFC 9457 fields on failure", () => {
  const problem = {
    title: "Not found",
    status: 404,
    detail: "no such memory: x",
    type: "about:blank",
  };
  try {
    unwrap({ error: problem, response: new Response(null, { status: 404 }) });
    throw new Error("expected unwrap to throw");
  } catch (error) {
    expect(isApiError(error)).toBe(true);
    expect((error as ApiError).status).toBe(404);
    expect((error as ApiError).title).toBe("Not found");
    expect((error as ApiError).detail).toBe("no such memory: x");
  }
});

test("unwrapVoid succeeds silently for a 204 with no body", () => {
  expect(() => unwrapVoid({ response: new Response(null, { status: 204 }) })).not.toThrow();
});

test("unwrapVoid still throws on a Problem response", () => {
  const problem = { title: "Conflict", status: 409, type: "about:blank" };
  expect(() =>
    unwrapVoid({ error: problem, response: new Response(null, { status: 409 }) }),
  ).toThrow(ApiError);
});
