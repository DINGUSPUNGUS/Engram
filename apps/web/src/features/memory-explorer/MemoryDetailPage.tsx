"use client";

import { useQueries } from "@tanstack/react-query";
import { CheckCircle2, History, Link2, Undo2, XCircle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ProvenancePanel } from "@/components/provenance";
import { ErrorState, LoadingState, QueryState } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiClient } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import {
  useAddEvidence,
  useAdjustImportance,
  useConfirmMemory,
  useContradictMemory,
  useMemory,
  useMemoryAt,
  useMemoryTimeline,
  useUndoMemory,
} from "@/lib/api/hooks/memories";
import { queryKeys } from "@/lib/api/keys";
import { formatDateTime, formatPercent } from "@/lib/format";

export function MemoryDetailPage({ memoryId }: { memoryId: string }) {
  const memory = useMemory(memoryId);

  return (
    <div className="flex flex-col gap-6">
      <QueryState query={memory}>
        {(data) => (
          <>
            <header className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-2xl font-semibold tracking-tight">{data.title}</h1>
                <Badge variant="outline">{data.kind}</Badge>
                {data.stale ? <Badge variant="warning">stale</Badge> : null}
                {data.archived ? <Badge variant="outline">archived</Badge> : null}
                {data.pinned ? <Badge variant="secondary">pinned</Badge> : null}
              </div>
              <p className="font-mono text-xs text-muted-foreground">
                {data.slug} · v{data.version}
              </p>
            </header>

            {data.content ? (
              <p className="whitespace-pre-wrap rounded-lg border border-border bg-card p-4 text-sm">
                {data.content}
              </p>
            ) : null}

            <div className="grid gap-6 lg:grid-cols-2">
              <SpineCard memoryId={memoryId} />
              <AttributesCard attributes={data.attributes} tags={data.tags} />
            </div>

            <EvidenceCard memoryId={memoryId} evidence={data.evidence} />
            <RelationshipsCard links={data.links} />
            <TimelineCard memoryId={memoryId} />
            <TimeTravelCard memoryId={memoryId} />
            <UndoCard memoryId={memoryId} />
          </>
        )}
      </QueryState>
    </div>
  );
}

function SpineCard({ memoryId }: { memoryId: string }) {
  const memory = useMemory(memoryId);
  const confirm = useConfirmMemory();
  const contradict = useContradictMemory();
  const [contradictingId, setContradictingId] = useState("");

  if (!memory.data) return null;
  const data = memory.data;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Confidence &amp; importance</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        <dl className="grid grid-cols-2 gap-2">
          <Metric label="Confidence" value={formatPercent(data.confidence)} />
          <Metric label="Effective confidence" value={formatPercent(data.effective_confidence)} />
          <Metric label="Visibility" value={data.visibility} />
          <Metric label="Lifetime" value={data.lifetime_policy} />
          <Metric
            label="Last confirmed"
            value={data.last_confirmed_at ? formatDateTime(data.last_confirmed_at) : "never"}
          />
          <Metric
            label="User weight"
            value={
              data.user_weight !== null && data.user_weight !== undefined
                ? formatPercent(data.user_weight)
                : "unset"
            }
          />
        </dl>

        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
          <Button
            size="sm"
            variant="outline"
            disabled={confirm.isPending}
            onClick={() => confirm.mutate({ memoryId })}
          >
            <CheckCircle2 className="h-3.5 w-3.5" /> Confirm
          </Button>
          <input
            value={contradictingId}
            onChange={(event) => setContradictingId(event.target.value)}
            placeholder="contradicting memory id (optional)"
            className="min-w-0 flex-1 rounded-md border border-input bg-background px-2 py-1 text-xs"
          />
          <Button
            size="sm"
            variant="outline"
            disabled={contradict.isPending}
            onClick={() =>
              contradict.mutate({ memoryId, contradictingId: contradictingId.trim() || undefined })
            }
          >
            <XCircle className="h-3.5 w-3.5" /> Contradict
          </Button>
        </div>
        {confirm.isError ? <ErrorState error={confirm.error} /> : null}
        {contradict.isError ? <ErrorState error={contradict.error} /> : null}

        <ImportanceControls
          memoryId={memoryId}
          pinned={data.pinned}
          userWeight={data.user_weight ?? undefined}
        />
      </CardContent>
    </Card>
  );
}

function ImportanceControls({
  memoryId,
  pinned,
  userWeight,
}: {
  memoryId: string;
  pinned: boolean;
  userWeight: number | undefined;
}) {
  const adjust = useAdjustImportance();
  const [weight, setWeight] = useState(userWeight ?? 0.5);

  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-border pt-3">
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={pinned}
          onChange={(event) => adjust.mutate({ memoryId, pinned: event.target.checked })}
          className="h-4 w-4 rounded border-input"
        />
        Pinned
      </label>
      <label className="flex items-center gap-2 text-sm">
        weight
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={weight}
          onChange={(event) => setWeight(Number(event.target.value))}
          onPointerUp={() => adjust.mutate({ memoryId, userWeight: weight })}
          className="w-24"
        />
        <span className="tabular-nums text-muted-foreground">{formatPercent(weight)}</span>
      </label>
      {adjust.isError ? <ErrorState error={adjust.error} /> : null}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

function AttributesCard({
  attributes,
  tags,
}: {
  attributes: Record<string, unknown>;
  tags: string[];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Attributes</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {tags.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {tags.map((tag) => (
              <Badge key={tag} variant="secondary">
                {tag}
              </Badge>
            ))}
          </div>
        ) : null}
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
          {Object.entries(attributes).map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="text-muted-foreground">{key}</dt>
              <dd className="break-words">
                {typeof value === "object" ? JSON.stringify(value) : String(value)}
              </dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}

function EvidenceCard({
  memoryId,
  evidence,
}: {
  memoryId: string;
  evidence: { evidence_type: string; value: string; note?: string | null; actor?: string | null }[];
}) {
  const addEvidence = useAddEvidence();
  const [value, setValue] = useState("");
  const [evidenceType, setEvidenceType] = useState("quote");

  return (
    <Card>
      <CardHeader>
        <CardTitle>Evidence</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {evidence.length === 0 ? (
          <p className="text-sm text-muted-foreground">No evidence recorded.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {evidence.map((item) => (
              <li
                key={`${item.evidence_type}:${item.value}:${item.note ?? ""}`}
                className="rounded-md border border-border p-2 text-sm"
              >
                <div className="flex items-center gap-2">
                  <Badge variant="outline">{item.evidence_type}</Badge>
                  {item.actor ? (
                    <span className="text-xs text-muted-foreground">{item.actor}</span>
                  ) : null}
                </div>
                <p className="mt-1 whitespace-pre-wrap">{item.value}</p>
                {item.note ? <p className="text-xs text-muted-foreground">{item.note}</p> : null}
              </li>
            ))}
          </ul>
        )}

        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!value.trim()) return;
            addEvidence.mutate(
              { memoryId, evidenceType, value: value.trim() },
              { onSuccess: () => setValue("") },
            );
          }}
          className="flex flex-wrap items-center gap-2 border-t border-border pt-3"
        >
          <select
            value={evidenceType}
            onChange={(event) => setEvidenceType(event.target.value)}
            className="rounded-md border border-input bg-background px-2 py-1 text-sm"
          >
            {["quote", "uri", "conversation", "document", "observation"].map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
          <input
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="evidence value"
            className="min-w-0 flex-1 rounded-md border border-input bg-background px-2 py-1 text-sm"
          />
          <Button type="submit" size="sm" disabled={addEvidence.isPending}>
            Add evidence
          </Button>
        </form>
        {addEvidence.isError ? <ErrorState error={addEvidence.error} /> : null}
      </CardContent>
    </Card>
  );
}

function RelationshipsCard({ links }: { links: { target_id: string; relation: string }[] }) {
  const targets = useQueries({
    queries: links.map((link) => ({
      queryKey: queryKeys.memory(link.target_id),
      queryFn: async () =>
        unwrap(
          await apiClient.GET("/api/v1/memories/{memory_id}", {
            params: { path: { memory_id: link.target_id } },
          }),
        ),
      staleTime: 30_000,
    })),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <Link2 aria-hidden="true" className="h-4 w-4" />
          Relationships
        </CardTitle>
      </CardHeader>
      <CardContent>
        {links.length === 0 ? (
          <p className="text-sm text-muted-foreground">No linked memories.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {links.map((link, index) => (
              <li
                key={`${link.relation}-${link.target_id}`}
                className="flex items-center gap-2 text-sm"
              >
                <Badge variant="outline">{link.relation}</Badge>
                <Link href={`/memories/${link.target_id}`} className="hover:underline">
                  {targets[index]?.data?.title ?? link.target_id}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function TimelineCard({ memoryId }: { memoryId: string }) {
  const timeline = useMemoryTimeline(memoryId);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <History aria-hidden="true" className="h-4 w-4" />
          Event history &amp; provenance
        </CardTitle>
      </CardHeader>
      <CardContent>
        <QueryState
          query={timeline}
          isEmpty={(data) => data.entries.length === 0}
          empty={<p className="text-sm text-muted-foreground">No history.</p>}
        >
          {(data) => (
            <ol className="flex flex-col gap-3">
              {data.entries.map((entry) => (
                <li key={entry.event_id} className="rounded-md border border-border p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-sm font-medium">{entry.event_type}</span>
                    <span className="text-xs text-muted-foreground">
                      v{entry.stream_seq} · {formatDateTime(entry.occurred_at)}
                    </span>
                  </div>
                  <div className="mt-2">
                    <ProvenancePanel provenance={entry.provenance} />
                  </div>
                </li>
              ))}
            </ol>
          )}
        </QueryState>
      </CardContent>
    </Card>
  );
}

function TimeTravelCard({ memoryId }: { memoryId: string }) {
  const [mode, setMode] = useState<"version" | "at">("version");
  const [version, setVersion] = useState(1);
  const [at, setAt] = useState("");
  const [selector, setSelector] = useState<{ version?: number; at?: string }>();

  const snapshot = useMemoryAt(memoryId, selector ?? {}, { enabled: selector !== undefined });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Time travel</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setSelector(mode === "version" ? { version } : { at });
          }}
          className="flex flex-wrap items-center gap-2 text-sm"
        >
          <select
            value={mode}
            onChange={(event) => setMode(event.target.value as "version" | "at")}
            className="rounded-md border border-input bg-background px-2 py-1"
          >
            <option value="version">By version</option>
            <option value="at">By timestamp</option>
          </select>
          {mode === "version" ? (
            <input
              type="number"
              min={1}
              value={version}
              onChange={(event) => setVersion(Number(event.target.value))}
              className="w-24 rounded-md border border-input bg-background px-2 py-1"
            />
          ) : (
            <input
              type="datetime-local"
              value={at}
              onChange={(event) => setAt(event.target.value)}
              className="rounded-md border border-input bg-background px-2 py-1"
            />
          )}
          <Button type="submit" size="sm" variant="outline">
            Reconstruct
          </Button>
        </form>

        {selector ? (
          snapshot.isPending ? (
            <LoadingState label="Reconstructing…" rows={1} />
          ) : snapshot.isError ? (
            <ErrorState error={snapshot.error} onRetry={snapshot.refetch} />
          ) : snapshot.data ? (
            <div className="rounded-md border border-border bg-muted/40 p-3 text-sm">
              <p className="font-medium">
                {snapshot.data.title}{" "}
                <span className="font-mono text-xs text-muted-foreground">
                  (v{snapshot.data.version})
                </span>
              </p>
              <p className="mt-1 whitespace-pre-wrap text-muted-foreground">
                {snapshot.data.content}
              </p>
              <p className="mt-2 text-xs text-muted-foreground">
                confidence {formatPercent(snapshot.data.confidence)} · {snapshot.data.visibility} ·{" "}
                {snapshot.data.deleted ? "deleted at this point" : "not deleted"}
              </p>
            </div>
          ) : null
        ) : null}
      </CardContent>
    </Card>
  );
}

function UndoCard({ memoryId }: { memoryId: string }) {
  const undo = useUndoMemory();
  const [confirming, setConfirming] = useState(false);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <Undo2 aria-hidden="true" className="h-4 w-4" />
          Undo last change
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <p className="text-sm text-muted-foreground">
          Compensates the most recent event on this memory with its inverse. Refused (409) if that
          event has no defined inverse — e.g. a prior delete.
        </p>
        {confirming ? (
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="destructive"
              disabled={undo.isPending}
              onClick={() => undo.mutate({ memoryId }, { onSettled: () => setConfirming(false) })}
            >
              Confirm undo
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </div>
        ) : (
          <Button size="sm" variant="outline" className="w-fit" onClick={() => setConfirming(true)}>
            Undo last change
          </Button>
        )}
        {undo.isError ? <ErrorState error={undo.error} /> : null}
        {undo.isSuccess ? (
          <p className="text-sm text-emerald-600 dark:text-emerald-400">
            Reverted. Compensating event {undo.data.compensating_event_id}.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
