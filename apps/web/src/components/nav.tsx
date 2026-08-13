"use client";

import {
  Activity,
  FileSearch,
  GitPullRequest,
  Home,
  LayoutList,
  Settings as SettingsIcon,
  Telescope,
  TerminalSquare,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { ConnectionBadge } from "@/components/connection-badge";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "Home", icon: Home },
  { href: "/memories", label: "Memory Explorer", icon: LayoutList },
  { href: "/proposals", label: "Proposal Review", icon: GitPullRequest },
  { href: "/timeline", label: "Timeline", icon: Activity },
  { href: "/observatory", label: "Observatory", icon: Telescope },
  { href: "/console", label: "Console", icon: TerminalSquare },
  { href: "/settings", label: "Settings", icon: SettingsIcon },
] as const;

/** Top-level nav — the seven M7 dashboard areas. Flat `flex-wrap` rather
 * than a collapsing hamburger menu: at seven items it never needs more
 * than two rows even on a phone-width viewport, so a JS-driven disclosure
 * would add a failure mode without adding usability. */
export function Nav() {
  const pathname = usePathname();

  return (
    <header className="border-b border-border">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <FileSearch aria-hidden="true" className="h-5 w-5" />
          <span className="font-semibold tracking-tight">engram</span>
        </div>
        <nav aria-label="Dashboard sections" className="flex flex-wrap gap-1">
          {LINKS.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? pathname === "/" : pathname?.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors",
                  active
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                )}
              >
                <Icon aria-hidden="true" className="h-4 w-4" />
                {label}
              </Link>
            );
          })}
        </nav>
        <ConnectionBadge />
      </div>
    </header>
  );
}
