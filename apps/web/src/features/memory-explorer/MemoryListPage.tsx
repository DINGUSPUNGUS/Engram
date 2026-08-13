"use client";

import { Search } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { useMemories } from "@/lib/api/hooks/memories";
import { useSearch } from "@/lib/api/hooks/search";
import { formatPercent } from "@/lib/format";

/**
 * Memory Explorer's landing screen: the Query Engine (ADR-0016) when a query
 * is typed, the plain listing otherwise. Both hit existing endpoints only —
 * there is no client-side filtering or a second query language here, just
 * whichever request the current input calls for.
 */
export function MemoryListPage() {
  const [query, setQuery] = useState("");
  const trimmed = query.trim();

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Memory Explorer</h1>
        <p className="text-muted-foreground">
          Search, browse, and inspect every memory in this space.
        </p>
      </div>

      <label className="flex items-center gap-2 rounded-md border border-input bg-background px-3 py-2">
        <Search aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
        <span className="sr-only">Search memories (engram query language)</span>
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="kind:project status:active tag:oss confidence>0.8 dark mode"
          className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        />
      </label>

      {trimmed.length > 0 ? <SearchResults query={trimmed} /> : <MemoryList />}
    </div>
  );
}

function SearchResults({ query }: { query: string }) {
  const search = useSearch(query);

  if (search.isPending) return <LoadingState label="Searching…" />;
  if (search.isError) return <ErrorState error={search.error} onRetry={search.refetch} />;
  if (!search.data || search.data.hits.length === 0) {
    return <EmptyState title="No matches" description={`Nothing matched "${query}".`} />;
  }

  return (
    <ul className="flex flex-col divide-y divide-border rounded-lg border border-border">
      {search.data.hits.map((hit) => (
        <li key={hit.memory_id} className="flex flex-col gap-1 p-3">
          <Link href={`/memories/${hit.memory_id}`} className="font-medium hover:underline">
            {hit.title}
          </Link>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="outline">{hit.kind}</Badge>
            <span>confidence {formatPercent(hit.effective_confidence)}</span>
            {hit.score !== null && hit.score !== undefined ? (
              <span>score {hit.score.toFixed(2)}</span>
            ) : null}
          </div>
          {hit.snippet ? <p className="text-sm text-muted-foreground">{hit.snippet}</p> : null}
        </li>
      ))}
    </ul>
  );
}

function MemoryList() {
  const [includeArchived, setIncludeArchived] = useState(false);
  const memories = useMemories({ includeArchived });

  return (
    <div className="flex flex-col gap-3">
      <label className="flex w-fit items-center gap-2 text-sm text-muted-foreground">
        <input
          type="checkbox"
          checked={includeArchived}
          onChange={(event) => setIncludeArchived(event.target.checked)}
          className="h-4 w-4 rounded border-input"
        />
        Include archived
      </label>

      {memories.isPending ? <LoadingState /> : null}
      {memories.isError ? <ErrorState error={memories.error} onRetry={memories.refetch} /> : null}
      {memories.data && memories.data.items.length === 0 ? (
        <EmptyState
          title="No memories yet"
          description="Approved proposals will appear here once merged."
        />
      ) : null}
      {memories.data && memories.data.items.length > 0 ? (
        <ul className="flex flex-col divide-y divide-border rounded-lg border border-border">
          {memories.data.items.map((memory) => (
            <li key={memory.id} className="flex items-center justify-between gap-3 p-3">
              <div className="flex flex-col gap-1">
                <Link href={`/memories/${memory.id}`} className="font-medium hover:underline">
                  {memory.title}
                </Link>
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <Badge variant="outline">{memory.kind}</Badge>
                  {memory.tags.map((tag) => (
                    <Badge key={tag} variant="secondary">
                      {tag}
                    </Badge>
                  ))}
                  {memory.stale ? <Badge variant="warning">stale</Badge> : null}
                  {memory.archived ? <Badge variant="outline">archived</Badge> : null}
                </div>
              </div>
              <span className="whitespace-nowrap text-sm text-muted-foreground">
                {formatPercent(memory.effective_confidence)}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
