import type { Metadata } from "next";
import type { ReactNode } from "react";

import { Nav } from "@/components/nav";
import { Providers } from "@/lib/query/Providers";

import "./globals.css";

export const metadata: Metadata = {
  title: "engram",
  description: "Git-native, event-sourced, user-owned memory for AI assistants.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground"
        >
          Skip to content
        </a>
        <Providers>
          <Nav />
          {/* biome-ignore lint/nursery/useUniqueElementIds: page-level singleton landmark; the skip-link href must target a fixed id, not a useId()-generated one. */}
          <main id="main" className="mx-auto max-w-6xl px-4 py-8">
            {children}
          </main>
        </Providers>
      </body>
    </html>
  );
}
