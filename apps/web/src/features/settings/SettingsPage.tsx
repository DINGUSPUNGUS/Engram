"use client";

import { QueryState } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useSettings } from "@/lib/api/hooks/system";

/**
 * Read-only configuration (`GET /api/v1/settings`). There is deliberately
 * no edit form here: nothing in the current architecture exposes a
 * configuration-mutation endpoint, and M7b is told not to invent one
 * without an explicit architectural contract for it.
 */
export function SettingsPage() {
  const settings = useSettings();

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">
          Read-only — reflects the running server's configuration.
        </p>
      </div>

      <QueryState query={settings}>
        {(data) => (
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Storage</CardTitle>
              </CardHeader>
              <CardContent>
                <dl className="flex flex-col gap-2 text-sm">
                  <Row label="Data directory" value={data.data_dir} mono />
                  <Row label="Database path" value={data.db_path} mono />
                </dl>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Git export</CardTitle>
                <CardDescription>Markdown + NDJSON portability layer (ADR-0017).</CardDescription>
              </CardHeader>
              <CardContent>
                <dl className="flex flex-col gap-2 text-sm">
                  <Row label="Repository path" value={data.export_repo_path} mono />
                  <div className="flex items-center justify-between">
                    <dt className="text-muted-foreground">Initialized</dt>
                    <dd>
                      {data.export_repo_initialized ? (
                        <Badge variant="success">yes</Badge>
                      ) : (
                        <Badge variant="outline">no</Badge>
                      )}
                    </dd>
                  </div>
                  <div className="flex items-center justify-between">
                    <dt className="text-muted-foreground">Managed files</dt>
                    <dd>{data.export_paths.length}</dd>
                  </div>
                </dl>
                {data.export_paths.length > 0 ? (
                  <ul className="mt-2 flex flex-col gap-0.5 border-t border-border pt-2 font-mono text-xs text-muted-foreground">
                    {data.export_paths.map((path) => (
                      <li key={path} className="truncate">
                        {path}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </CardContent>
            </Card>

            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>Assistant capabilities</CardTitle>
                <CardDescription>
                  What the AssistantGateway (ADR-0020) accepts from connected assistants.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-1.5">
                  {data.assistant_capabilities.map((capability) => (
                    <Badge key={capability} variant="secondary">
                      {capability}
                    </Badge>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </QueryState>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={mono ? "truncate font-mono text-xs" : ""}>{value}</dd>
    </div>
  );
}
