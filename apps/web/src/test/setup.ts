import { cleanup, configure } from "@testing-library/react";
import { afterAll, afterEach } from "vitest";
import { server } from "@/test/msw/server";
import { resetMockState } from "@/test/msw/state";

// The default 1000ms async-utility timeout (findBy*/waitFor) is tight for
// tests that exercise real MSW round trips under this suite's full
// parallel run; a slower CI/dev machine shouldn't turn a correct test
// flaky. Individual tests still fail fast on a genuine bug — this only
// raises how long a query waits for data that's actually coming.
configure({ asyncUtilTimeout: 5000 });

// Started at module top level, not inside `beforeAll`: `@engram/api-client`
// resolves `fetch` from `globalThis` once, at `createClient()` time, which
// runs the moment any test file imports `apiClient` — before vitest would
// run a `beforeAll` hook. Patching `globalThis.fetch` has to happen before
// that import, so it happens here, synchronously, as this setup file loads.
server.listen({ onUnhandledRequest: "error" });

afterEach(() => {
  cleanup();
  server.resetHandlers();
  resetMockState();
});
afterAll(() => server.close());
