# ADR-0018: Proposal drafts are intents; merge decides; undo compensates

- **Status**: accepted (2026-07-14)
- **Deciders**: project owner (M4 directive), implementation session
- **Refines**: ADR-0002 (event sourcing), ADR-0011 (proposals), ADR-0017 (import)

## Context

M4 makes proposals real: approve, reject, merge, undo, conflict detection, and a
reconciler that turns external edits into reviewable diffs. Three decisions are not
covered by existing ADRs and get decided here, before implementation:

1. **What does a proposal carry?** M3's importer stored draft dicts shaped like
   events. But an event is a *fact that already happened* — pre-minting facts
   inverts the mantra. If drafts were events, merging would append them verbatim,
   skipping the aggregate's invariants against *current* state.
2. **What is a conflict?** Projections are disposable; deciding merges against them
   would make the review pipeline depend on rebuildable state.
3. **What does undo mean** in a log that must never be mutated?

## Decision

### 1. Drafts are intents, not events

A proposal carries **draft intents** (`draft_schema_version: 2`): declarative
operations — `create_memory`, `edit_memory`, `tag_memory`, `update_attributes`,
`link_memories`, `unlink_memories`, `add_evidence`, `set_visibility`,
`set_lifetime` — each recording the target stream and the **`base_version`** (the
target's aggregate version when the proposal was opened; `0` for creates).

**Merge is the only event producer.** At merge, each intent is re-driven through
the Memory aggregate's `decide_*` methods against the stream's *current* folded
state — the same invariants, validation, and no-op elision as any live command.
The aggregate decides; the merge merely asks. A v1 draft (M3's event-shaped dicts)
is upcast to an intent at interpretation time, so M3 proposals remain mergeable —
logs replay forever.

All events produced by one merge — every affected memory stream plus the
`ProposalMerged` record — are appended in **one atomic batch**: a merge either
happens completely or not at all.

### 2. Conflicts are detected against stream history

At merge start, for every stream a proposal touches:
`current stream head version != recorded base_version` ⇒ **conflict**
(`StaleVersionError`; nothing is appended). The comparison uses the event stream
(fold of history), never projection rows. Within a single merge, drafts for the
same stream apply sequentially onto the evolving in-memory aggregate — internal
progression is not a conflict; only movement that happened *outside* the proposal
is.

This is deliberately strict (version equality, not semantic mergeability). A
conflicted proposal is rejected-and-reimported, not auto-resolved: the system
never silently picks a winner (memory-model.md §8). Field-level three-way merge
can be layered on later without changing the contract, because drafts carry
everything needed to recompute against a new base.

### 3. Undo is compensation, never erasure

`undo` on a **merged** proposal appends, atomically:

- a **compensating event** per merged event, in reverse order —
  `MemoryCreated → MemoryDeleted` (user-initiated, so ADR-0011 holds),
  `MemoryEdited/AttributesUpdated → inverse edit` (prior values recovered by
  folding the stream up to just before the event — the M2 time-travel machinery),
  `MemoryTagged → mirrored MemoryTagged`, `MemoryLinked ↔ MemoryUnlinked`,
  `MemoryEvidenceAdded → MemoryEvidenceRetracted` (new event; see below),
  `MemoryVisibilityChanged/LifetimeChanged → inverse with prior values`;
- `ProposalUndone` on the proposal stream (new event; status → `undone`).

**Undo guard**: every affected stream's head must still be the last event that
merge appended. If anything happened since, undo refuses (`ConflictError`) —
compensating around later changes would silently pick winners. History is never
rewritten; the log tells the whole story: proposed, merged, undone.

**New event types** (registry + upcasters as usual):

- `MemoryEvidenceRetracted(seq)` — evidence stays append-only *as a log*: a
  retraction is itself an appended fact. Current state drops the entry; history
  keeps both the evidence and its retraction. Required because reversibility is a
  frozen principle and evidence previously had no inverse.
- `ProposalUndone(note, compensating_event_ids)`.

### 4. External edits reconcile; they never duplicate

When the importer meets a document whose `id` already exists in the store, it
**reconciles**: fold the current aggregate (from the stream, not projections),
compute the semantic difference (title/content/slug, tag sets, per-key attributes,
link sets, evidence additions), and emit **edit intents** — never a second
`MemoryCreated`. Unchanged documents contribute nothing; a fully-unchanged import
opens no proposal. Documents for tombstoned memories are rejected (resurrection is
a human decision, not an import side effect). Evidence *removals* in a file are
ignored: retraction is an explicit reviewed action, not a file edit.

## Consequences

- The mantra becomes mechanical: nothing but a human-approved merge (or a live
  user command) makes the aggregate emit events.
- Merge output is a deterministic function of (event log, drafts); event ids and
  timestamps are minted at merge like any command — provenance, not decisions.
- Undo of an undo is just another proposal-shaped problem and is out of scope; the
  log supports it whenever it earns its place.
- Strict version conflicts will reject some merges a smarter differ could save.
  Accepted: predictability over cleverness ("boringly trustworthy").
- The state projection's evidence `seq` becomes sparse after retraction; new
  evidence takes `max(seq)+1`, never reuses a retracted slot.

## Alternatives rejected

1. **Drafts as pre-minted events, appended verbatim on merge** — skips current-state
   invariants; stale payloads could corrupt state; inverts "events decide".
2. **Conflict detection on projection rows** — couples the trust pipeline to
   disposable state; a drifted projection could approve a conflicting merge.
3. **Undo by deleting merged events** — forbidden by the append-only log
   (SQLite triggers enforce it), and it would falsify history.
4. **Auto-merge on conflict (last-writer-wins / field union)** — silently picks
   winners; rejected by the iron rule of memory-model.md §8.
