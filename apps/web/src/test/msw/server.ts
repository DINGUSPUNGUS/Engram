import { setupServer } from "msw/node";

import { handlers } from "@/test/msw/handlers";

/** One MSW server for the whole test run; individual tests override
 * handlers with `server.use(...)` for error/edge cases. */
export const server = setupServer(...handlers);
