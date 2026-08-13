"use client";

import { useState } from "react";

import { ErrorState, LoadingState } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useEventFeed } from "@/lib/api/hooks/events";
import { useMemoryAt, useMemoryTimeline } from "@/lib/api/hooks/memories";
import { useProposalTimeline } from "@/lib/api/hooks/proposals";
import { useSearch } from "@/lib/api/hooks/search";
import { useRebuild, useStats } from "@/lib/api/hooks/system";

/**
 * Developer console over the same endpoints every other screen uses — no
 * second query language, no raw-SQL escape hatch, just a faster way to
 * exercise `/search`, `/events`, timelines, time travel, and `/stats` +
 * `/admin/rebuild` for debugging.
 */
export function ConsolePage() {
  const [tab, setTab] = useState("search");

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Console</h1>
        <p className="text-muted-foreground">
          Direct, developer-oriented access to the same public API.
        </p>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="search">Search</TabsTrigger>
          <TabsTrigger value="events">Events</TabsTrigger>
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
          <TabsTrigger value="time-travel">Time travel</TabsTrigger>
          <TabsTrigger value="stats">Stats &amp; rebuild</TabsTrigger>
        </TabsList>

        <TabsContent value="search" className="mt-4">
          <SearchTab />
        </TabsContent>
        <TabsContent value="events" className="mt-4">
          <EventsTab />
        </TabsContent>
        <TabsContent value="timeline" className="mt-4">
          <TimelineTab />
        </TabsContent>
        <TabsContent value="time-travel" className="mt-4">
          <TimeTravelTab />
        </TabsContent>
        <TabsContent value="stats" className="mt-4">
          <StatsTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function SearchTab() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const search = useSearch(submitted);

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 pt-4">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setSubmitted(query);
          }}
          className="flex gap-2"
        >
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="engram query language"
            className="flex-1 rounded-md border border-input bg-background px-2 py-1 font-mono text-sm"
          />
          <Button type="submit" size="sm">
            Run
          </Button>
        </form>
        {submitted ? (
          search.isPending ? (
            <LoadingState rows={2} />
          ) : search.isError ? (
            <ErrorState error={search.error} />
          ) : (
            <pre className="overflow-x-auto rounded-md border border-border bg-muted p-3 text-xs">
              {JSON.stringify(search.data, null, 2)}
            </pre>
          )
        ) : null}
      </CardContent>
    </Card>
  );
}

function EventsTab() {
  const [after, setAfter] = useState(0);
  const [limit, setLimit] = useState(20);
  const feed = useEventFeed(after, limit);

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 pt-4">
        <div className="flex items-center gap-2 text-sm">
          <label className="flex items-center gap-1">
            after
            <input
              type="number"
              value={after}
              onChange={(event) => setAfter(Number(event.target.value))}
              className="w-24 rounded-md border border-input bg-background px-2 py-1"
            />
          </label>
          <label className="flex items-center gap-1">
            limit
            <input
              type="number"
              value={limit}
              onChange={(event) => setLimit(Number(event.target.value))}
              className="w-20 rounded-md border border-input bg-background px-2 py-1"
            />
          </label>
          <Button size="sm" variant="outline" onClick={() => feed.refetch()}>
            Fetch
          </Button>
        </div>
        {feed.isPending ? <LoadingState rows={2} /> : null}
        {feed.isError ? <ErrorState error={feed.error} /> : null}
        {feed.data ? (
          <pre className="overflow-x-auto rounded-md border border-border bg-muted p-3 text-xs">
            {JSON.stringify(feed.data, null, 2)}
          </pre>
        ) : null}
      </CardContent>
    </Card>
  );
}

function TimelineTab() {
  const [kind, setKind] = useState<"memory" | "proposal">("memory");
  const [id, setId] = useState("");
  const [submitted, setSubmitted] = useState("");

  const memoryTimeline = useMemoryTimeline(kind === "memory" ? submitted || undefined : undefined);
  const proposalTimeline = useProposalTimeline(
    kind === "proposal" ? submitted || undefined : undefined,
  );
  const result = kind === "memory" ? memoryTimeline : proposalTimeline;

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 pt-4">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setSubmitted(id.trim());
          }}
          className="flex items-center gap-2"
        >
          <select
            value={kind}
            onChange={(event) => setKind(event.target.value as "memory" | "proposal")}
            className="rounded-md border border-input bg-background px-2 py-1 text-sm"
          >
            <option value="memory">memory</option>
            <option value="proposal">proposal</option>
          </select>
          <input
            value={id}
            onChange={(event) => setId(event.target.value)}
            placeholder="id (uuid)"
            className="flex-1 rounded-md border border-input bg-background px-2 py-1 font-mono text-sm"
          />
          <Button type="submit" size="sm">
            Inspect
          </Button>
        </form>
        {submitted ? (
          result.isPending ? (
            <LoadingState rows={2} />
          ) : result.isError ? (
            <ErrorState error={result.error} />
          ) : (
            <pre className="overflow-x-auto rounded-md border border-border bg-muted p-3 text-xs">
              {JSON.stringify(result.data, null, 2)}
            </pre>
          )
        ) : null}
      </CardContent>
    </Card>
  );
}

function TimeTravelTab() {
  const [id, setId] = useState("");
  const [version, setVersion] = useState(1);
  const [selector, setSelector] = useState<{ id: string; version: number }>();
  const snapshot = useMemoryAt(selector?.id, { version: selector?.version });

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 pt-4">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setSelector({ id: id.trim(), version });
          }}
          className="flex items-center gap-2"
        >
          <input
            value={id}
            onChange={(event) => setId(event.target.value)}
            placeholder="memory id (uuid)"
            className="flex-1 rounded-md border border-input bg-background px-2 py-1 font-mono text-sm"
          />
          <input
            type="number"
            min={1}
            value={version}
            onChange={(event) => setVersion(Number(event.target.value))}
            className="w-20 rounded-md border border-input bg-background px-2 py-1"
          />
          <Button type="submit" size="sm">
            Reconstruct
          </Button>
        </form>
        {selector ? (
          snapshot.isPending ? (
            <LoadingState rows={2} />
          ) : snapshot.isError ? (
            <ErrorState error={snapshot.error} />
          ) : (
            <pre className="overflow-x-auto rounded-md border border-border bg-muted p-3 text-xs">
              {JSON.stringify(snapshot.data, null, 2)}
            </pre>
          )
        ) : null}
      </CardContent>
    </Card>
  );
}

function StatsTab() {
  const stats = useStats();
  const rebuild = useRebuild();
  const [confirming, setConfirming] = useState(false);

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 pt-4">
        {stats.isPending ? <LoadingState rows={2} /> : null}
        {stats.isError ? <ErrorState error={stats.error} onRetry={stats.refetch} /> : null}
        {stats.data ? (
          <pre className="overflow-x-auto rounded-md border border-border bg-muted p-3 text-xs">
            {JSON.stringify(stats.data, null, 2)}
          </pre>
        ) : null}

        <div className="flex items-center gap-2 border-t border-border pt-3">
          {confirming ? (
            <>
              <Button
                size="sm"
                variant="destructive"
                disabled={rebuild.isPending}
                onClick={() => rebuild.mutate(undefined, { onSettled: () => setConfirming(false) })}
              >
                Confirm rebuild
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                Cancel
              </Button>
            </>
          ) : (
            <Button size="sm" variant="outline" onClick={() => setConfirming(true)}>
              Rebuild projections
            </Button>
          )}
          {rebuild.isSuccess ? (
            <Badge variant="success">replayed {rebuild.data.events_replayed} events</Badge>
          ) : null}
        </div>
        {rebuild.isError ? <ErrorState error={rebuild.error} /> : null}
      </CardContent>
    </Card>
  );
}
