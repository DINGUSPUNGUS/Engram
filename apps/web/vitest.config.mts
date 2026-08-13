import path from "node:path";

import { defineConfig } from "vitest/config";

// No @vitejs/plugin-react: that plugin exists for dev-server features
// (fast refresh) this project's `vitest run` never uses. esbuild's native
// automatic JSX transform (below) is all `vitest run` needs, and skipping
// the plugin avoids depending on Vite's own version at all.
export default defineConfig({
  esbuild: {
    jsx: "automatic",
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test/setup.ts"],
    // This sandbox has limited effective parallelism; spinning up a dozen
    // jsdom environments at once starves each one enough that testing-
    // library's async queries occasionally miss even a generous timeout.
    // Running files sequentially trades wall-clock time for a suite that
    // is reliably green rather than flaky under load.
    fileParallelism: false,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
});
