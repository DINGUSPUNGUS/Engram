"use client";

import { AlertTriangle, CheckCircle2, FolderGit2 } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { QueryState } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useRecentEvents } from "@/lib/api/hooks/events";
import { useSettings, useStats } from "@/lib/api/hooks/system";
import { streamHref } from "@/lib/eventRouting";
import { formatRelativeTime } from "@/lib/format";

/**
 * Home — the at-a-glance space health screen. Every number on this page is
 * read verbatim from `GET /api/v1/stats` and `GET /api/v1/settings`; nothing
 * here computes a count, a health status, or a drift determination — those
 * are exactly the kind of derived judgment ADR-0021 §1 reserves for the
 * server.
 */
export function HomePage() {
  const stats = useStats();
  const settings = useSettings();
  const recent = useRecentEvents(10);

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Home</h1>
        <p className="text-muted-foreground">
          Space statistics, projection health, and recent activity.
        </p>
      </div>

      <QueryState query={stats}>
        {(data) => (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard label="Memories" value={data.memory_count} />
            <StatCard label="Proposals" value={data.proposal_count} />
            <StatCard label="Events" value={data.event_count} />
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Projections</CardDescription>
              </CardHeader>
              <CardContent>
                <span className="inline-flex items-center gap-1.5 text-lg font-semibold">
                  {data.drifted ? (
                    <>
                      <AlertTriangle aria-hidden="true" className="h-4 w-4 text-amber-500" />
                      Drifted
                    </>
                  ) : (
                    <>
                      <CheckCircle2 aria-hidden="true" className="h-4 w-4 text-emerald-500" />
                      Up to date
                    </>
                  )}
                </span>
              </CardContent>
            </Card>
          </div>
        )}
      </QueryState>

      <section className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Projection health</CardTitle>
            <CardDescription>Checkpoint vs. event-log head, per projection.</CardDescription>
          </CardHeader>
          <CardContent>
            <QueryState query={stats}>
              {(data) => (
                <ul className="flex flex-col gap-2">
                  {data.projections.map((projection) => (
                    <li
                      key={projection.name}
                      className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm"
                    >
                      <span className="font-mono">{projection.name}</span>
                      <span className="flex items-center gap-2">
                        <span className="text-muted-foreground">
                          checkpoint {projection.checkpoint}
                        </span>
                        {projection.lag > 0 ? (
                          <Badge variant="warning">lag {projection.lag}</Badge>
                        ) : (
                          <Badge variant="success">current</Badge>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </QueryState>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-1.5">
              <FolderGit2 aria-hidden="true" className="h-4 w-4" />
              Repository &amp; export status
            </CardTitle>
            <CardDescription>Read-only — see Settings to change configuration.</CardDescription>
          </CardHeader>
          <CardContent>
            <QueryState query={settings}>
              {(data) => (
                <dl className="flex flex-col gap-2 text-sm">
                  <Row label="Export repo">
                    {data.export_repo_initialized ? (
                      <Badge variant="success">initialized</Badge>
                    ) : (
                      <Badge variant="outline">not initialized</Badge>
                    )}
                  </Row>
                  <Row label="Export path">
                    <span className="font-mono text-xs">{data.export_repo_path}</span>
                  </Row>
                  <Row label="Managed files">
                    <span>{data.export_paths.length}</span>
                  </Row>
                </dl>
              )}
            </QueryState>
          </CardContent>
        </Card>
      </section>

      <Card>
        <CardHeader>
          <CardTitle>Recent activity</CardTitle>
          <CardDescription>The last events appended to the log, newest first.</CardDescription>
        </CardHeader>
        <CardContent>
          <QueryState
            query={recent}
            isEmpty={(data) => data.items.length === 0}
            empty={
              <p className="text-sm text-muted-foreground">No events yet — this space is empty.</p>
            }
          >
            {(data) => (
              <ul className="flex flex-col divide-y divide-border">
                {data.items.map((event) => {
                  const href = streamHref(event.event_type, event.stream_id);
                  return (
                    <li
                      key={event.event_id}
                      className="flex items-center justify-between gap-3 py-2 text-sm"
                    >
                      <div className="flex flex-col">
                        {href ? (
                          <Link href={href} className="font-medium hover:underline">
                            {event.event_type}
                          </Link>
                        ) : (
                          <span className="font-medium">{event.event_type}</span>
                        )}
                        <span className="text-xs text-muted-foreground">by {event.actor}</span>
                      </div>
                      <time dateTime={event.occurred_at} className="text-xs text-muted-foreground">
                        {formatRelativeTime(event.occurred_at)}
                      </time>
                    </li>
                  );
                })}
              </ul>
            )}
          </QueryState>
        </CardContent>
      </Card>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
      </CardHeader>
      <CardContent>
        <span className="text-2xl font-semibold tabular-nums">{value.toLocaleString()}</span>
      </CardContent>
    </Card>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
