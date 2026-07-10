import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Internal packages ship TypeScript source; Next transpiles them in place.
  transpilePackages: ["@engram/api-client", "@engram/ui"],
  // Self-contained server bundle for docker/web.Dockerfile. Opt-in via env:
  // standalone tracing symlinks require privileges Windows dev boxes lack.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
};

export default nextConfig;
