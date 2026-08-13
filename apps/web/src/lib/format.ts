/** Presentation-only formatting. Nothing here interprets or derives domain
 * meaning — nothing on this page decides what a value *means*, only how a
 * value the server already computed gets printed. */

const dateTimeFormatter = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium",
  timeStyle: "medium",
});

export function formatDateTime(iso: string): string {
  try {
    return dateTimeFormatter.format(new Date(iso));
  } catch {
    return iso;
  }
}

const relativeFormatter = new Intl.RelativeTimeFormat("en-US", { numeric: "auto" });
const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 31536000],
  ["month", 2592000],
  ["day", 86400],
  ["hour", 3600],
  ["minute", 60],
  ["second", 1],
];

export function formatRelativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  const diffSeconds = Math.round((then.getTime() - now.getTime()) / 1000);
  const abs = Math.abs(diffSeconds);
  for (const [unit, secondsInUnit] of UNITS) {
    if (abs >= secondsInUnit || unit === "second") {
      return relativeFormatter.format(Math.round(diffSeconds / secondsInUnit), unit);
    }
  }
  return relativeFormatter.format(0, "second");
}

export function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

/** Renders free-form `Provenance.detail` defensively (ADR-0022 §4): a
 * structured object when it parses as JSON, the raw string otherwise. */
export function tryParseJson(raw: string): Record<string, unknown> | string {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
    return raw;
  } catch {
    return raw;
  }
}
