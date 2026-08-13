"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * A small hand-rolled tab set (WAI-ARIA "Tabs" pattern: roving tabindex,
 * arrow-key navigation, `aria-selected`/`aria-controls` wiring) rather than
 * a dependency — Console and Proposal Detail are the only two consumers,
 * which doesn't clear the bar for pulling in a component library primitive.
 */
interface TabsContextValue {
  value: string;
  setValue: (value: string) => void;
  idBase: string;
}

const TabsContext = React.createContext<TabsContextValue | null>(null);

function useTabsContext(component: string): TabsContextValue {
  const ctx = React.useContext(TabsContext);
  if (!ctx) throw new Error(`<${component}> must be used inside <Tabs>`);
  return ctx;
}

export function Tabs({
  value,
  onValueChange,
  className,
  children,
}: {
  value: string;
  onValueChange: (value: string) => void;
  className?: string;
  children: React.ReactNode;
}) {
  const idBase = React.useId();
  return (
    <TabsContext.Provider value={{ value, setValue: onValueChange, idBase }}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  );
}

export function TabsList({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  const listRef = React.useRef<HTMLDivElement>(null);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    const tabs = Array.from(
      listRef.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]') ?? [],
    );
    const currentIndex = tabs.findIndex((tab) => tab === document.activeElement);
    if (currentIndex === -1) return;
    event.preventDefault();
    const delta = event.key === "ArrowRight" ? 1 : -1;
    const next = tabs[(currentIndex + delta + tabs.length) % tabs.length];
    next?.focus();
    next?.click();
  };

  return (
    <div
      ref={listRef}
      role="tablist"
      onKeyDown={onKeyDown}
      className={cn("inline-flex gap-1 rounded-md border border-border bg-muted p-1", className)}
    >
      {children}
    </div>
  );
}

export function TabsTrigger({ value, children }: { value: string; children: React.ReactNode }) {
  const ctx = useTabsContext("TabsTrigger");
  const selected = ctx.value === value;
  return (
    <button
      type="button"
      role="tab"
      id={`${ctx.idBase}-tab-${value}`}
      aria-selected={selected}
      aria-controls={`${ctx.idBase}-panel-${value}`}
      tabIndex={selected ? 0 : -1}
      onClick={() => ctx.setValue(value)}
      className={cn(
        "rounded-sm px-3 py-1.5 text-sm font-medium transition-colors",
        selected
          ? "bg-background text-foreground shadow-sm"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

export function TabsContent({
  value,
  className,
  children,
}: {
  value: string;
  className?: string;
  children: React.ReactNode;
}) {
  const ctx = useTabsContext("TabsContent");
  if (ctx.value !== value) return null;
  return (
    <div
      role="tabpanel"
      id={`${ctx.idBase}-panel-${value}`}
      aria-labelledby={`${ctx.idBase}-tab-${value}`}
      className={className}
    >
      {children}
    </div>
  );
}
