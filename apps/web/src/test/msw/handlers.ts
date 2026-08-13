import { HttpResponse, http } from "msw";

import {
  appendEvent,
  appendTimelineEntry,
  db,
  type MockMemory,
  type MockProposal,
  snapshotMemory,
} from "@/test/msw/state";

/** RFC 9457 problem response, mirroring `engram_api.errors`. */
function problem(status: number, title: string, detail: string) {
  return HttpResponse.json(
    { type: "about:blank", title, status, detail, instance: "/test" },
    { status, headers: { "Content-Type": "application/problem+json" } },
  );
}

function newMemoryFromDraft(draft: Record<string, unknown>, actor: string): MockMemory {
  const id = String(draft.memory_id ?? crypto.randomUUID());
  const memory: MockMemory = {
    id,
    kind: String(draft.kind ?? "fact"),
    slug: String(draft.slug ?? "memory"),
    title: String(draft.title ?? "Untitled"),
    content: String(draft.content ?? ""),
    attributes: (draft.attributes as Record<string, unknown>) ?? {},
    tags: (draft.tags as string[]) ?? [],
    links: [],
    evidence: [],
    confidence: typeof draft.confidence === "number" ? draft.confidence : 0.8,
    effective_confidence: typeof draft.confidence === "number" ? draft.confidence : 0.8,
    stale: false,
    last_confirmed_at: null,
    lifetime_policy: String(draft.lifetime_policy ?? "standard"),
    lifetime_until: null,
    visibility: String(draft.visibility ?? "shared"),
    pinned: false,
    user_weight: null,
    archived: false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    version: 1,
  };
  db.memories.set(id, memory);
  snapshotMemory(memory);
  const event = appendEvent(id, "MemoryCreated", actor);
  appendTimelineEntry(db.memoryTimelines, id, event);
  return memory;
}

export const handlers = [
  // -- system -----------------------------------------------------------
  http.get("*/api/v1/stats", () => {
    return HttpResponse.json({
      event_count: db.events.length,
      head_global_seq: db.events.length,
      memory_count: db.memories.size,
      proposal_count: db.proposals.size,
      projections: [
        { name: "state", checkpoint: db.events.length, lag: 0 },
        { name: "search", checkpoint: db.events.length, lag: 0 },
      ],
      drifted: false,
    });
  }),

  http.get("*/api/v1/settings", () => {
    return HttpResponse.json({
      data_dir: "/tmp/engram-test",
      db_path: "/tmp/engram-test/engram.db",
      export_repo_path: "/tmp/engram-test/export",
      export_repo_initialized: true,
      export_paths: ["manifest.json", "memories/example.md"],
      assistant_capabilities: [
        "proposal_submission",
        "retrieval",
        "streaming",
        "timeline",
        "tool_calling",
      ],
    });
  }),

  http.post("*/admin/rebuild", () => {
    return HttpResponse.json({ events_replayed: db.events.length }, { status: 202 });
  }),

  // -- search -------------------------------------------------------------
  http.get("*/api/v1/search", ({ request }) => {
    const q = new URL(request.url).searchParams.get("q") ?? "";
    if (q.includes(">>")) return problem(422, "Validation failed", "malformed query");
    const needle = q.toLowerCase();
    const hits = [...db.memories.values()]
      .filter(
        (m) => m.title.toLowerCase().includes(needle) || m.content.toLowerCase().includes(needle),
      )
      .map((m) => ({
        memory_id: m.id,
        kind: m.kind,
        slug: m.slug,
        title: m.title,
        snippet: m.content.slice(0, 80) || null,
        score: 1,
        effective_confidence: m.effective_confidence,
      }));
    return HttpResponse.json({ query: q, hits, next_cursor: null });
  }),

  // -- events ---------------------------------------------------------------
  http.get("*/api/v1/events", ({ request }) => {
    const url = new URL(request.url);
    const after = Number(url.searchParams.get("after") ?? "0");
    const limit = Number(url.searchParams.get("limit") ?? "50");
    const page = db.events.filter((e) => e.global_seq > after).slice(0, limit);
    const next_after = page.length === limit ? (page.at(-1)?.global_seq ?? null) : null;
    return HttpResponse.json({ items: page, next_after });
  }),

  // -- memories ---------------------------------------------------------------
  http.get("*/api/v1/memories", () => {
    return HttpResponse.json({ items: [...db.memories.values()], next_cursor: null });
  }),

  http.get("*/api/v1/memories/:id", ({ params }) => {
    const memory = db.memories.get(String(params.id));
    if (!memory) return problem(404, "Not found", `no such memory: ${params.id}`);
    return HttpResponse.json(memory);
  }),

  http.get("*/api/v1/memories/:id/timeline", ({ params }) => {
    const entries = db.memoryTimelines.get(String(params.id)) ?? [];
    return HttpResponse.json({ memory_id: params.id, entries });
  }),

  http.get("*/api/v1/memories/:id/at", ({ params, request }) => {
    const versions = db.memorySnapshots.get(String(params.id));
    if (!versions) return problem(404, "Not found", `no such memory: ${params.id}`);
    const version = Number(new URL(request.url).searchParams.get("version") ?? "0");
    const snapshot = versions[version - 1];
    if (!snapshot) return problem(404, "Not found", `no such version: ${version}`);
    return HttpResponse.json({
      id: snapshot.id,
      kind: snapshot.kind,
      slug: snapshot.slug,
      title: snapshot.title,
      content: snapshot.content,
      attributes: snapshot.attributes,
      tags: snapshot.tags,
      confidence: snapshot.confidence,
      lifetime_policy: snapshot.lifetime_policy,
      visibility: snapshot.visibility,
      archived: snapshot.archived,
      deleted: false,
      version: snapshot.version,
    });
  }),

  http.post("*/api/v1/memories/:id/undo", ({ params }) => {
    const id = String(params.id);
    const memory = db.memories.get(id);
    const versions = db.memorySnapshots.get(id);
    if (!memory || !versions) return problem(404, "Not found", `no such memory: ${id}`);
    if (versions.length < 2) {
      return problem(409, "Conflict", "no compensator exists for this event type");
    }
    const prior = versions[versions.length - 2];
    if (!prior) return problem(409, "Conflict", "no compensator exists for this event type");
    const reverted: MockMemory = {
      ...memory,
      title: prior.title,
      content: prior.content,
      version: memory.version + 1,
    };
    db.memories.set(id, reverted);
    snapshotMemory(reverted);
    const event = appendEvent(id, "MemoryEdited", "test-reviewer");
    appendTimelineEntry(db.memoryTimelines, id, event);
    return HttpResponse.json({ memory: reverted, compensating_event_id: event.event_id });
  }),

  http.post("*/api/v1/memories/:id/confirm", ({ params }) => {
    const id = String(params.id);
    const memory = db.memories.get(id);
    if (!memory) return problem(404, "Not found", `no such memory: ${id}`);
    const updated = {
      ...memory,
      confidence: Math.min(1, memory.confidence + 0.1),
      last_confirmed_at: new Date().toISOString(),
    };
    db.memories.set(id, updated);
    const event = appendEvent(id, "MemoryConfirmed", "test-reviewer");
    appendTimelineEntry(db.memoryTimelines, id, event);
    return HttpResponse.json(updated);
  }),

  // -- proposals ---------------------------------------------------------------
  http.get("*/api/v1/proposals", ({ request }) => {
    const status = new URL(request.url).searchParams.get("status");
    const items = [...db.proposals.values()]
      .filter((p) => !status || p.status === status)
      .map((p) => ({
        id: p.id,
        title: p.title,
        status: p.status,
        review_note: p.review_note,
        draft_count: p.drafts.length,
        opened_by: p.opened_by,
        created_at: p.created_at,
        updated_at: p.updated_at,
      }));
    return HttpResponse.json({ items, next_cursor: null });
  }),

  http.post("*/api/v1/proposals", async ({ request }) => {
    const body = (await request.json()) as {
      title: string;
      description?: string;
      proposed_events?: Record<string, unknown>[];
    };
    if (!body.proposed_events || body.proposed_events.length === 0) {
      return problem(422, "Validation failed", "a proposal needs at least one draft");
    }
    const id = crypto.randomUUID();
    const proposal: MockProposal = {
      id,
      title: body.title,
      description: body.description ?? "",
      status: "pending",
      review_note: null,
      drafts: body.proposed_events,
      merged_event_ids: [],
      version: 1,
      opened_by: "test-assistant",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    db.proposals.set(id, proposal);
    const event = appendEvent(id, "ProposalOpened", "test-assistant");
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
    return HttpResponse.json(proposal, { status: 201 });
  }),

  http.get("*/api/v1/proposals/:id", ({ params }) => {
    const proposal = db.proposals.get(String(params.id));
    if (!proposal) return problem(404, "Not found", `no such proposal: ${params.id}`);
    return HttpResponse.json(proposal);
  }),

  http.get("*/api/v1/proposals/:id/timeline", ({ params }) => {
    const entries = db.proposalTimelines.get(String(params.id)) ?? [];
    return HttpResponse.json({ proposal_id: params.id, entries });
  }),

  http.post("*/api/v1/proposals/:id/approve", async ({ params, request }) => {
    const id = String(params.id);
    const proposal = db.proposals.get(id);
    if (!proposal) return problem(404, "Not found", `no such proposal: ${id}`);
    if (proposal.status !== "pending") {
      return problem(409, "Conflict", `cannot approve a ${proposal.status} proposal`);
    }
    const body = (await request.json().catch(() => ({}))) as { note?: string };
    const updated: MockProposal = {
      ...proposal,
      status: "approved",
      review_note: body.note ?? null,
    };
    db.proposals.set(id, updated);
    const event = appendEvent(id, "ProposalApproved", "test-reviewer");
    appendTimelineEntry(db.proposalTimelines, id, event);
    return HttpResponse.json(updated);
  }),

  http.post("*/api/v1/proposals/:id/reject", async ({ params, request }) => {
    const id = String(params.id);
    const proposal = db.proposals.get(id);
    if (!proposal) return problem(404, "Not found", `no such proposal: ${id}`);
    if (proposal.status !== "pending") {
      return problem(409, "Conflict", `cannot reject a ${proposal.status} proposal`);
    }
    const body = (await request.json().catch(() => ({}))) as { note?: string };
    const updated: MockProposal = {
      ...proposal,
      status: "rejected",
      review_note: body.note ?? null,
    };
    db.proposals.set(id, updated);
    const event = appendEvent(id, "ProposalRejected", "test-reviewer");
    appendTimelineEntry(db.proposalTimelines, id, event);
    return HttpResponse.json(updated);
  }),

  http.post("*/api/v1/proposals/:id/merge", ({ params }) => {
    const id = String(params.id);
    const proposal = db.proposals.get(id);
    if (!proposal) return problem(404, "Not found", `no such proposal: ${id}`);
    if (proposal.status !== "approved") {
      return problem(
        409,
        "Conflict",
        `cannot merge a ${proposal.status} proposal — approve it first`,
      );
    }
    const appended: string[] = [];
    for (const draft of proposal.drafts) {
      if (draft.op === "create_memory") {
        newMemoryFromDraft(draft, "test-reviewer");
        const memoryEvent = db.events.at(-1);
        if (memoryEvent) appended.push(memoryEvent.event_id);
      }
    }
    const updated: MockProposal = { ...proposal, status: "merged", merged_event_ids: appended };
    db.proposals.set(id, updated);
    const event = appendEvent(id, "ProposalMerged", "test-reviewer");
    appendTimelineEntry(db.proposalTimelines, id, event);
    return HttpResponse.json({ proposal: updated, appended_event_ids: appended });
  }),

  http.post("*/api/v1/proposals/:id/undo", ({ params }) => {
    const id = String(params.id);
    const proposal = db.proposals.get(id);
    if (!proposal) return problem(404, "Not found", `no such proposal: ${id}`);
    if (proposal.status !== "merged") {
      return problem(409, "Conflict", `cannot undo a ${proposal.status} proposal`);
    }
    // Revert every memory this proposal created.
    for (const draft of proposal.drafts) {
      if (draft.op === "create_memory") {
        const memoryId = String(draft.memory_id);
        const memory = db.memories.get(memoryId);
        if (memory) {
          db.memories.delete(memoryId);
          const event = appendEvent(memoryId, "MemoryDeleted", "test-reviewer");
          appendTimelineEntry(db.memoryTimelines, memoryId, event);
        }
      }
    }
    const updated: MockProposal = { ...proposal, status: "undone" };
    db.proposals.set(id, updated);
    const event = appendEvent(id, "ProposalUndone", "test-reviewer");
    appendTimelineEntry(db.proposalTimelines, id, event);
    return HttpResponse.json({ proposal: updated, compensating_event_ids: [event.event_id] });
  }),
];
