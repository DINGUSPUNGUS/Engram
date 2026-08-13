"use client";

import { Badge } from "@/components/ui/badge";
import { tryParseJson } from "@/lib/format";

interface ProvenanceLike {
  actor: string;
  session_id?: string | null;
  detail?: string | null;
}

/**
 * Renders `ProvenanceView` the way ADR-0022 §4 requires: a structured panel
 * when `detail` parses as JSON, the raw string verbatim when it doesn't,
 * and an explicit "no pipeline provenance recorded" when there is none. It
 * never fabricates a provider, model, or prompt version, and never infers
 * one from surrounding events — unknown keys are shown, not dropped, so a
 * richer future explanation is visible without a UI change.
 *
 * Shared by Memory Explorer, Proposal Review, Timeline, and Observatory —
 * one component, not four re-implementations of the same degrade path.
 */
export function ProvenancePanel({ provenance }: { provenance: ProvenanceLike }) {
  return (
    <div className="flex flex-col gap-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted-foreground">actor</span>
        <Badge variant="outline">{provenance.actor}</Badge>
        {provenance.session_id ? (
          <>
            <span className="text-muted-foreground">session</span>
            <Badge variant="outline" className="font-mono">
              {provenance.session_id}
            </Badge>
          </>
        ) : null}
      </div>
      <DetailPanel detail={provenance.detail ?? null} />
    </div>
  );
}

function DetailPanel({ detail }: { detail: string | null }) {
  if (!detail) {
    return <p className="text-sm italic text-muted-foreground">no pipeline provenance recorded</p>;
  }

  const parsed = tryParseJson(detail);
  if (typeof parsed === "string") {
    return (
      <pre className="overflow-x-auto rounded-md border border-border bg-muted p-2 text-xs whitespace-pre-wrap">
        {parsed}
      </pre>
    );
  }

  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-md border border-border bg-muted/50 p-2 text-xs">
      {Object.entries(parsed).map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="font-mono text-muted-foreground">{key}</dt>
          <dd className="break-words font-mono">
            {typeof value === "object" ? JSON.stringify(value) : String(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}
