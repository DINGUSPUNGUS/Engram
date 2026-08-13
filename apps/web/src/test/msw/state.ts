/**
 * A minimal, stateful in-memory stand-in for the real engram API — enough
 * of the actual event-sourcing behavior (append-only event log, proposal
 * open→approve→merge→undo, memory undo-by-compensation, time travel by
 * version) to drive the dashboard's real code paths end to end in tests,
 * without a running Python server. This is test infrastructure, not
 * product code: nothing here is imported by `src/features/**` or `src/lib/**`.
 */

export interface MockEvent {
  global_seq: number;
  event_id: string;
  stream_id: string;
  stream_seq: number;
  event_type: string;
  occurred_at: string;
  actor: string;
}

export interface MockProvenance {
  actor: string;
  session_id: string | null;
  detail: string | null;
}

export interface MockTimelineEntry {
  event_id: string;
  event_type: string;
  occurred_at: string;
  stream_seq: number;
  provenance: MockProvenance;
}

export interface MockMemory {
  id: string;
  kind: string;
  slug: string;
  title: string;
  content: string;
  attributes: Record<string, unknown>;
  tags: string[];
  links: { target_id: string; relation: string }[];
  evidence: { evidence_type: string; value: string; note: string | null; actor: string | null }[];
  confidence: number;
  effective_confidence: number;
  stale: boolean;
  last_confirmed_at: string | null;
  lifetime_policy: string;
  lifetime_until: string | null;
  visibility: string;
  pinned: boolean;
  user_weight: number | null;
  archived: boolean;
  created_at: string;
  updated_at: string;
  version: number;
}

export interface MockProposal {
  id: string;
  title: string;
  description: string;
  status: "draft" | "pending" | "approved" | "rejected" | "merged" | "undone";
  review_note: string | null;
  drafts: Record<string, unknown>[];
  merged_event_ids: string[];
  version: number;
  opened_by: string;
  created_at: string;
  updated_at: string;
}

let seq = 0;
let now = Date.parse("2026-08-13T10:00:00Z");

export const db = {
  memories: new Map<string, MockMemory>(),
  memorySnapshots: new Map<string, MockMemory[]>(), // by memory id, index 0 = version 1
  memoryTimelines: new Map<string, MockTimelineEntry[]>(),
  proposals: new Map<string, MockProposal>(),
  proposalTimelines: new Map<string, MockTimelineEntry[]>(),
  events: [] as MockEvent[],
};

export function resetMockState(): void {
  seq = 0;
  now = Date.parse("2026-08-13T10:00:00Z");
  db.memories.clear();
  db.memorySnapshots.clear();
  db.memoryTimelines.clear();
  db.proposals.clear();
  db.proposalTimelines.clear();
  db.events = [];
}

function nextTimestamp(): string {
  now += 1000;
  return new Date(now).toISOString();
}

export function appendEvent(streamId: string, eventType: string, actor: string): MockEvent {
  seq += 1;
  const event: MockEvent = {
    global_seq: seq,
    event_id: crypto.randomUUID(),
    stream_id: streamId,
    stream_seq: seq,
    event_type: eventType,
    occurred_at: nextTimestamp(),
    actor,
  };
  db.events.push(event);
  return event;
}

export function appendTimelineEntry(
  map: Map<string, MockTimelineEntry[]>,
  streamId: string,
  event: MockEvent,
  detail: string | null = null,
): void {
  const entries = map.get(streamId) ?? [];
  entries.push({
    event_id: event.event_id,
    event_type: event.event_type,
    occurred_at: event.occurred_at,
    stream_seq: entries.length + 1,
    provenance: { actor: event.actor, session_id: "test-session", detail },
  });
  map.set(streamId, entries);
}

export function snapshotMemory(memory: MockMemory): void {
  const list = db.memorySnapshots.get(memory.id) ?? [];
  list.push({ ...memory });
  db.memorySnapshots.set(memory.id, list);
}

const DEFAULTS: MockMemory = {
  id: "",
  kind: "fact",
  slug: "seeded-memory",
  title: "Seeded memory",
  content: "",
  attributes: {},
  tags: [],
  links: [],
  evidence: [],
  confidence: 0.8,
  effective_confidence: 0.8,
  stale: false,
  last_confirmed_at: null,
  lifetime_policy: "standard",
  lifetime_until: null,
  visibility: "shared",
  pinned: false,
  user_weight: null,
  archived: false,
  created_at: new Date(0).toISOString(),
  updated_at: new Date(0).toISOString(),
  version: 1,
};

/** Test-only fixture helper: inserts a memory directly (bypassing the
 * proposal/merge flow) for tests that only need a memory to already exist.
 * The full open→approve→merge path is exercised separately by the
 * end-to-end workflow test. */
export function seedMemory(overrides: Partial<MockMemory> = {}): MockMemory {
  const id = overrides.id ?? crypto.randomUUID();
  const memory: MockMemory = { ...DEFAULTS, ...overrides, id };
  db.memories.set(id, memory);
  snapshotMemory(memory);
  const event = appendEvent(id, "MemoryCreated", "test-fixture");
  appendTimelineEntry(db.memoryTimelines, id, event);
  return memory;
}

/** A single well-formed `create_memory` draft — the same op the real
 * `CreateMemoryDraft.to_dict()` produces (engram_core.application.commands.drafts). */
export function createMemoryDraft(
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    draft_schema_version: 2,
    op: "create_memory",
    memory_id: crypto.randomUUID(),
    kind: "preference",
    slug: "prefers-dark-mode",
    title: "Prefers dark mode",
    content: "User said they prefer dark mode.",
    attributes: { polarity: "likes", strength: 0.8, context: "UI" },
    attributes_schema_version: 1,
    tags: ["ui"],
    confidence: 0.8,
    lifetime_policy: "permanent",
    lifetime_until: null,
    visibility: "private",
    base_version: 0,
    ...overrides,
  };
}

export function seedProposal(overrides: Partial<MockProposal> = {}): MockProposal {
  const id = overrides.id ?? crypto.randomUUID();
  const proposal: MockProposal = {
    id,
    title: "Remember UI preference",
    description: "extracted from chat",
    status: "pending",
    review_note: null,
    drafts: [createMemoryDraft()],
    merged_event_ids: [],
    version: 1,
    opened_by: "test-assistant",
    created_at: new Date(0).toISOString(),
    updated_at: new Date(0).toISOString(),
    ...overrides,
  };
  db.proposals.set(id, proposal);
  const event = appendEvent(id, "ProposalOpened", proposal.opened_by);
  appendTimelineEntry(
    db.proposalTimelines,
    id,
    event,
    JSON.stringify({
      provider: "fake",
      model: "fake-model",
      prompt_versions: { "candidate-generation": 1 },
    }),
  );
  return proposal;
}
