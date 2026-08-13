"use client";

import { AlertTriangle, Inbox, RefreshCw } from "lucide-react";
import { type ReactNode, useMemo } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { isApiError } from "@/lib/api/errors";

/** Loading placeholder. `<output aria-live="polite">` so assistive tech
 * announces "loading" once instead of reading skeleton markup. */
export function LoadingState({ label = "Loading…", rows = 3 }: { label?: string; rows?: number }) {
  // Skeleton rows are interchangeable placeholders with no identity of their
  // own — a stable synthetic key (not the array index) avoids the
  // index-as-key smell without pretending these rows represent real data.
  const rowKeys = useMemo(() => Array.from({ length: rows }, () => crypto.randomUUID()), [rows]);
  return (
    <output aria-live="polite" className="flex flex-col gap-2">
      <span className="sr-only">{label}</span>
      {rowKeys.map((key) => (
        <Skeleton key={key} className="h-12 w-full" />
      ))}
    </output>
  );
}

export function EmptyState({ title, description }: { title: string; description?: string }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border p-8 text-center">
      <Inbox aria-hidden="true" className="h-6 w-6 text-muted-foreground" />
      <p className="font-medium">{title}</p>
      {description ? <p className="text-sm text-muted-foreground">{description}</p> : null}
    </div>
  );
}

/** Renders any thrown error as a problem the user can act on. Prefers the
 * RFC 9457 fields (title/detail/status) when the failure is an `ApiError`;
 * falls back to a generic message for anything else (a network drop, a
 * parse failure) rather than leaking a raw stack trace into the UI. */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const title = isApiError(error) ? error.title : "Something went wrong";
  const detail = isApiError(error)
    ? error.detail
    : error instanceof Error
      ? error.message
      : undefined;
  const status = isApiError(error) ? error.status : undefined;

  return (
    <div
      role="alert"
      className="flex flex-col gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-4"
    >
      <div className="flex items-center gap-2 text-destructive">
        <AlertTriangle aria-hidden="true" className="h-4 w-4" />
        <p className="font-medium">
          {title}
          {status ? (
            <span className="ml-1 font-mono text-xs text-muted-foreground">({status})</span>
          ) : null}
        </p>
      </div>
      {detail ? <p className="text-sm text-muted-foreground">{detail}</p> : null}
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex w-fit items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-sm hover:bg-accent"
        >
          <RefreshCw aria-hidden="true" className="h-3.5 w-3.5" />
          Retry
        </button>
      ) : null}
    </div>
  );
}

interface QueryLike<T> {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  data: T | undefined;
  refetch: () => void;
}

/**
 * The one place loading/error/empty/data branching happens for a query —
 * every feature area renders its data through this rather than
 * re-implementing the same four-way branch. `isEmpty` is caller-supplied
 * because "empty" means something different per resource (no items, no
 * hits, zero-length timeline).
 */
export function QueryState<T>({
  query,
  loading,
  isEmpty,
  empty,
  children,
}: {
  query: QueryLike<T>;
  loading?: ReactNode;
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <>{loading ?? <LoadingState />}</>;
  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;
  if (query.data === undefined) return <ErrorState error={query.error} onRetry={query.refetch} />;
  if (isEmpty?.(query.data)) return <>{empty ?? <EmptyState title="Nothing here yet" />}</>;
  return <>{children(query.data)}</>;
}
