# The Memory Model

**Status: the Phase 0.5 deliverable — the most load-bearing document in the repository.**
This model is designed to survive 100,000+ memories without fundamental change. Everything
else (storage, API, extraction, pruning) derives from it. Changes here require an ADR and
a very good reason.

Companion decisions: [ADR-0008](adr/0008-typed-kinds-over-aggregates.md) (why kinds are
schemas, not aggregates), [ADR-0009](adr/0009-justification-spine.md) (signals stored,
scores derived), [ADR-0010](adr/0010-graph-semantics.md) (two-tier graph),
[ADR-0011](adr/0011-pruning-via-proposals.md) (nothing is ever silently deleted).

---

## 1. The two-level model: one mechanism, twelve kinds

A memory is **not a blob of markdown**. Every memory is a typed object with structured,
queryable attributes. But the twelve kinds do not become twelve aggregates — that would
duplicate the stream/lifecycle/undo machinery twelve times and make kind #13 a rewrite.
Instead:

- **The mechanism is singular.** One event-sourced `Memory` aggregate owns identity,
  lifecycle, the metadata spine (§3), links, and versioning — identically for every kind.
- **The shape is per-kind.** Each kind has a **versioned attribute schema**: a frozen
  dataclass validated at command time, stored as structured data, projected into
  queryable SQL. `Project.status` is a real field with a closed vocabulary, not a
  markdown convention.

```
Memory (the mechanism: stream, spine, links, lifecycle)
└── kind + attributes (the shape: validated per-kind schema, versioned)
    ├── fact          an atomic assertion
    ├── preference    a like/dislike/want/avoid with strength and context
    ├── person        a human the user knows or references
    ├── organization  a company, team, community, institution
    ├── project       an undertaking with status and participants
    ├── skill         an ability with proficiency and evidence
    ├── goal          an intended outcome with horizon and status
    ├── contact       a communication channel owned by a person/org
    ├── event         something that happened at a time (episodic)
    ├── location      a place
    ├── asset         a thing owned/used: file, document, device, account, domain
    └── relationship  a reified edge: subject —predicate→ object, with evidence
```

`kind` is **immutable after creation**. A Person never becomes a Location; a
misclassified memory is superseded by a new one (`supersedes` edge), preserving history.

Kind schemas are registered in a **KindRegistry** (mirror of the event registry):
`(kind, schema_version, attributes dataclass, upcasters)`. Old attribute payloads upcast
on read, exactly like events. Adding kind #13 = one dataclass + one registration + one
projection view — no new aggregate, no new tables.

`content` (markdown) remains on every memory as the **narrative rendering** — the
human-readable elaboration, the part the markdown export shows. Attributes are the
queryable truth; content is the story around it. Neither substitutes for the other.

## 2. The twelve kind schemas (v1)

Attribute fields below are the structured, validated, queryable fields. All are optional
unless marked ●. Links noted as `→kind` are typed edges (§6), not embedded copies.

| Kind | Attributes (v1) | Notes |
| --- | --- | --- |
| **fact** | `statement` ● | The atom. Everything else it relates to is edges (`about →` any kind). |
| **preference** | `polarity` ● (`likes·dislikes·wants·avoids·prefers`), `strength` (0–1), `context` (e.g. "food", "code-style") | Contradiction handling: coexist if contexts differ, else supersede (§8). |
| **person** | `full_name` ●, `aliases[]`, `roles[]`, `notes` | Affiliations = `works_at →organization` edges. Contact info = `contact` memories with `owned_by →person`. Alias set feeds entity resolution (§9). |
| **organization** | `name` ●, `aliases[]`, `org_type` (`company·team·community·institution·other`), `url` | |
| **project** | `name` ●, `status` ● (`idea·active·paused·done·abandoned`), `summary`, `target_date` | Participants = `involves →person` edges. Related memories = inbound `about` edges — free, via the graph. |
| **skill** | `name` ●, `proficiency` (`novice·competent·proficient·expert`), `last_used_at` | Evidence of proficiency lives in the spine's evidence list. |
| **goal** | `statement` ●, `horizon` (`short·medium·long`), `status` ● (`active·achieved·dropped`), `target_date` | Hierarchy = `part_of →goal` edges. |
| **contact** | `channel` ● (`email·phone·handle·address·other`), `value` ●, `label` ("work", "personal"), `preferred` (bool) | Always linked `owned_by →person|organization`. Separate from person so channels have their own confidence/lifetime (numbers change). |
| **event** | `occurred_at` ● (or `start_at`/`end_at`), `outcome` | Episodic. Participants `involves →person`, place `located_in →location`. Decays fastest (§7). |
| **location** | `name` ●, `address`, `latitude`/`longitude`, `location_type` (`home·work·city·venue·other`) | |
| **asset** | `asset_type` ● (`file·document·device·account·domain·repository·other`), `uri`, `identifier`, `notes` | Ownership = `owned_by →person|organization` edge. |
| **relationship** | `subject_id` ●, `predicate` ●, `object_id` ●, `since`, `until` | The reified edge (§6): use when the connection itself needs confidence, evidence, and lifetime ("Alice manages Bob, since 2024, per standup 3/12"). |

Vocabulary rule: every closed vocabulary above is a `StrEnum` in code. Extending one is a
schema version bump with an upcaster, reviewed like any event schema change.

## 3. The justification spine

**Every memory must answer: "why does this deserve to exist?"** The answer is machine-
readable and lives on every memory object, regardless of kind:

| Field | Type | What it answers |
| --- | --- | --- |
| `source` | `Provenance` (creation) | Who put this here? (user, which assistant, which session) |
| `evidence` | `tuple[EvidenceRef, ...]` | What supports it? (quote, URI, conversation, document, observation) — append-only |
| `confidence` | `float 0..1` | How sure are we it's true? (§5) |
| `last_confirmed_at` | `datetime?` | When did a human or corroborating source last vouch for it? |
| `importance` | `ImportanceSignals` | Why does it matter? — pinned flag, explicit user weight, access history (§7 derives the score) |
| `lifetime` | `RetentionPolicy` | How long should it live? (§4) |
| `visibility` | `Visibility` | Who may recall it? (`private · shared · restricted`) |

`EvidenceRef = (evidence_type: quote·uri·conversation·document·observation, value, note?)`.
Evidence is never edited or removed — corrections add new evidence.

`Visibility`: `shared` (default — any connected assistant may recall), `private` (only
surfaces in the dashboard/CLI, never to assistants), `restricted` (allow-listed actors;
the allow-list is an attribute of the restriction, checked at recall time). Visibility is
enforced at the query/recall boundary — the interface layer never sees what it may not
return.

Design rule ([ADR-0009](adr/0009-justification-spine.md)): **signals are stored in the
event log; scores are derived in projections.** `confidence` inputs, access history, and
pins are events; `importance_score` and `retention_score` are computed columns that can be
re-tuned and recomputed for the entire corpus at any time without touching history.

## 4. Lifecycle

```
                    (inside a Proposal)
                         proposed
                            │ merge
                            ▼
              ┌─────────► active ◄──────────┐
              │             │               │ MemoryConfirmed
   MemoryRestored           │ (derived)     │ (resets staleness)
              │             ▼               │
          archived ◄──── stale ─────────────┘
              │  ▲ MemoryArchived (user, or pruning proposal, or lifetime expiry)
              │
              │ MemoryDeleted (tombstone)
              ▼
           deleted  — stream persists forever; state row removed
```

- **proposed** — exists only as draft events inside a Proposal; not recallable.
- **active** — normal state.
- **stale** — *derived, not evented*: effective confidence (§5) has fallen below the
  kind's staleness threshold, or `lifetime` says it needs re-confirmation. Stale memories
  are still recallable but flagged, down-ranked, and queued for review.
- **archived** — hidden from recall, kept in state tables, restorable. Reached by user
  action, an accepted pruning proposal, or lifetime expiry.
- **deleted** — tombstoned. The event stream is never erased (append-only log); the state
  row is removed and the markdown file deleted in the next export commit.

`RetentionPolicy` (the `lifetime` field): `permanent` (never auto-archived: pins,
identity-level facts) · `standard` (subject to decay, the default) · `until` (explicit
expiry date — e.g. "parking spot C4 until Friday") · `ephemeral` (auto-archive after the
kind's short horizon; session-scoped context).

## 5. Confidence model

`confidence ∈ [0,1]` answers "how sure are we this is (still) true."

- **Priors by source** (constants live in one config module, tunable): user-stated ≈ 0.95,
  assistant-inferred ≈ 0.60, imported/reconciled ≈ 0.70.
- **`MemoryConfirmed`** (actor, optional evidence): moves confidence toward 1 —
  `c' = c + (1−c)·w`, where `w` is the confirmer's weight (user > assistant). Sets
  `last_confirmed_at`. Attaching corroborating evidence is a weak confirm.
- **`MemoryContradicted`** (pointer to the contradicting memory/evidence): decays
  confidence multiplicatively — `c' = c·(1−w)` — and creates a `contradicts` edge. Below
  the review threshold ⇒ the pair enters the conflict queue (§8).
- **Effective confidence** decays with time since `last_confirmed_at ?? created_at` using
  the kind's half-life (§7 table): `c_eff = c · 2^(−Δt / halflife)`. Derived at query
  time / in the projection — never written back to the log.
- `c_eff` below the kind's staleness threshold ⇒ **stale** (§4).

Confidence never changes without an event or the passage of time. There is no code path
that silently edits it.

## 6. Graph semantics — two tiers

([ADR-0010](adr/0010-graph-semantics.md))

**Tier 1 — lightweight edges** (`Link`): directed, typed, no identity of their own.
Created by `MemoryLinked` on the *source* memory's stream; materialized in the `links`
projection for traversal. The closed core vocabulary, with canonical direction:

| Relation | Canonical direction | Inverse (query name only) |
| --- | --- | --- |
| `about` | any memory → the entity it concerns | `subject_of` |
| `involves` | project/event/goal → person/org | `involved_in` |
| `part_of` | member → whole (goal→goal, project→project, location→location) | `contains` |
| `owned_by` | contact/asset → person/org | `owns` |
| `works_at` | person → organization | `employs` |
| `located_in` | anything → location | `location_of` |
| `relates_to` | symmetric, the weakest link | — |
| `supersedes` | new → old | `superseded_by` |
| `derived_from` | conclusion → source memory | `basis_of` |
| `contradicts` | symmetric | — |

Rules: store only the canonical direction (inverses are query-time aliases); no
self-links; duplicate `(source, target, relation)` is a conflict; kind schemas declare
which relations they may emit (validated at decide time). Extending the vocabulary = ADR.

**Tier 2 — reified relationships** (kind = `relationship`): when the *connection itself*
is knowledge — it needs confidence, evidence, lifetime, and history — it becomes a full
memory object with `subject_id`, `predicate`, `object_id`. Rule of thumb: if you would
ever need to confirm, contradict, or date the connection, reify it; otherwise use an edge.

**Integrity:** edges may dangle temporarily (target merged/archived) — traversal skips
dead ends; a maintenance projection reports them. Edge degree feeds centrality in the
retention score (§7). No cascading deletes, ever: archiving a Person never deletes their
Projects.

## 7. Importance, decay, and pruning

Stored signals (events): `pinned`, `user_weight` (explicit 0–1 override),
`MemoryAccessed` history. Derived (projection, recomputable): `access_count`,
`last_accessed_at`, link centrality, and:

```
retention_score = wr·recency + wf·log(1+access_count) + wc·centrality
                + wq·c_eff + wu·user_weight        (pinned ⇒ exempt)

recency = 2^(−time_since_last_access / halflife(kind))
```

Kind half-lives (v1 defaults; one tunable table, never hard-coded at call sites):

| Kind | Half-life | Staleness threshold (`c_eff`) |
| --- | --- | --- |
| person, organization, location | 730 d | 0.30 |
| preference, skill, fact | 365 d | 0.35 |
| goal, project (active exempt), asset, relationship, contact | 180 d | 0.40 |
| event (episodic) | 30 d | 0.50 |

**Pruning is a proposal, never a delete** ([ADR-0011](adr/0011-pruning-via-proposals.md)):
a background pass ranks unpinned memories by `retention_score`; those below threshold are
batched into an *archive Proposal* with the scores as evidence. A human (or an explicitly
configured auto-approve policy) merges it. The event log records exactly why every memory
was archived — pruning is as auditable as creation.

## 8. Conflict resolution

Conflict classes and default strategies (per-kind overrides in the same config table):

| Class | Detected by | Default resolution |
| --- | --- | --- |
| **Duplicate** (same real-world thing twice) | Entity resolution on alias/name/channel overlap (phase 8); manual merge anytime | `MemoryMerged` → survivor keeps id, source archived with `superseded_by` edge; alias sets union |
| **Contradiction** (incompatible assertions) | `MemoryContradicted` (explicit, by assistant or user); attribute-equality checks on structured fields | Human review via conflict queue. Preferences with different `context` coexist; same context ⇒ newest proposed as superseding. Facts require confirmation to win. |
| **Staleness** (probably outdated) | `c_eff` below threshold | Down-rank + confirmation request; unconfirmed ⇒ eligible for the pruning proposal |

Iron rule: **resolution is evented and reviewable — the system never silently picks a
winner.** Automation may *propose*; only confirmation/merge events *decide*.

## 9. Identity & entity resolution

- Identity is the UUIDv7 stream id, immutable (ADR-0003). Slugs and filenames remain
  mutable projections.
- Entity kinds (person, organization, location, asset) carry alias sets; resolution
  candidates come from alias/name/contact overlap. Resolution = `MemoryMerged` (§8):
  the survivor's stream absorbs meaning, the source stream survives as history.
- A memory is *about* entities via `about` edges — extraction (phase 8) resolves mentions
  to entity ids or proposes new entities, always through Proposals.

## 10. Event taxonomy (delta over docs/events.md)

The spine and kinds extend the memory event vocabulary:

| Event | Purpose |
| --- | --- |
| `MemoryCreated` | now carries `kind`, `attributes`, `confidence`, `lifetime`, `visibility` |
| `MemoryAttributesUpdated` | sparse change to kind-schema fields (validated) |
| `MemoryConfirmed` | vouching: raises confidence, sets `last_confirmed_at` |
| `MemoryContradicted` | disputes: lowers confidence, creates `contradicts` edge |
| `MemoryEvidenceAdded` | appends an `EvidenceRef` |
| `MemoryImportanceAdjusted` | pin/unpin, explicit `user_weight` |
| `MemoryVisibilityChanged` | private/shared/restricted transitions |
| `MemoryLifetimeChanged` | retention policy changes |

(Existing: Edited, EditedExternally, Tagged, Linked/Unlinked, Merged,
Archived/Restored, Deleted, Accessed — unchanged.)

## 11. Storage projection (how kinds stay queryable)

- `memories` table gains the spine: `kind`, `confidence`, `last_confirmed_at`,
  `lifetime`, `visibility`, `pinned`, `user_weight`, and `attributes` (JSON, validated
  before write — the DB stores only schema-valid payloads).
- `evidence` table: `(memory_id, seq, evidence_type, value, note, occurred_at, actor)`.
- Kind-specific querying: SQLite **expression indexes** on hot JSON fields (e.g.
  `json_extract(attributes,'$.status')` for projects) + one SQL **view per kind**
  (`view_projects`, `view_people`, …) exposing attributes as typed columns. Views are
  projection artifacts — dropped and recreated freely; no EAV, no 12 physical tables.
- Scores (`retention_score`, `importance_score`) live in a recomputable scoring
  projection, refreshed by `engram rebuild` or the (future) maintenance pass.

## 12. What this model deliberately does not do

- No probabilistic truth maintenance beyond the single confidence scalar — a full
  belief-revision system is not worth its complexity here.
- No user-defined kinds (yet): kind #13 is a PR with a schema + ADR, not runtime config.
  Revisit when plugins land (roadmap phase 9).
- No cross-space references: a memory space is a hard boundary.
- No automatic conflict *decisions*: automation proposes, events decide (§8).
