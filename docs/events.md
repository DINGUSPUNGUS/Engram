# Event Catalog

The vocabulary of everything that can happen. Code of record:
`libs/engram-core/src/engram_core/domain/events.py` (payloads) and
`libs/engram-events/` (envelope, registry, serde).

## Envelope

Every event travels in an `EventEnvelope`:

| Field | Meaning |
| --- | --- |
| `event_id` | UUIDv7, globally unique |
| `stream_id` | The aggregate's UUID |
| `stream_seq` | 1-based position in the stream; optimistic-concurrency token |
| `event_type` | Registered name, e.g. `MemoryCreated` |
| `schema_version` | Payload schema version; upcasters migrate on read |
| `payload` | Registered frozen dataclass |
| `occurred_at` | UTC timestamp |
| `provenance` | `actor` (user / claude / chatgpt / system / …), session, detail |
| `global_seq` | Total order, assigned by the store on append |

## Memory events

Creation & content:

| Event | Emitted when | Payload highlights |
| --- | --- | --- |
| `MemoryCreated` | A typed memory is born | id, **kind**, slug, title, content, **attributes** (+schema version), tags, confidence, lifetime, visibility |
| `MemoryEdited` | Narrative change (title/content/slug) | sparse fields; kind is immutable |
| `MemoryAttributesUpdated` | Kind-schema fields change | sparse `changes` dict, validated against the KindRegistry |
| `MemoryEditedExternally` | *(specified, not yet produced — see below)* | changed fields + source path |

Justification spine (memory-model.md §3, §5):

| Event | Emitted when | Payload highlights |
| --- | --- | --- |
| `MemoryConfirmed` | Someone vouched for it | note, **weight** (resolved from policy at decide time — ADR-0019); fold: c' = c + (1−c)·w, resets staleness |
| `MemoryContradicted` | Someone disputed it | contradicting_id, note, **weight**; fold: c' = c·(1−w); a companion `MemoryLinked` carries the contradicts edge |
| `MemoryConfidenceRestored` | Undo compensated a confirm/contradict (ADR-0019 §2) | confidence, last_confirmed_at, reason — emitted ONLY by proposal undo, no command produces it |
| `MemoryEvidenceAdded` | Support attached | evidence_type, value, note (append-only) |
| `MemoryEvidenceRetracted` | Undo compensated an evidence addition (ADR-0018) | seq (1-based add order), reason — the log keeps both the evidence and its retraction |
| `MemoryImportanceAdjusted` | Pin/unpin, explicit weight | pinned?, user_weight?, clear_user_weight (restoring "unset" is expressible — ADR-0019) |
| `MemoryVisibilityChanged` | Recall audience changes | visibility, allowed_actors |
| `MemoryLifetimeChanged` | Retention policy changes | policy, until |

Organization & lifecycle:

| Event | Emitted when | Payload highlights |
| --- | --- | --- |
| `MemoryTagged` | Tags added/removed | added, removed |
| `MemoryLinked` / `MemoryUnlinked` | Tier-1 graph edge change | target_id, relation (closed vocabulary) |
| `MemoryMerged` | *(specified, not yet produced — `merge_memories` raises `NotImplementedError`; M5 candidate generation opens proposals only)* | source_id, merged_content |
| `MemoryArchived` / `MemoryRestored` | Soft hide / unhide | reason |
| `MemoryDeleted` | Tombstone (log persists; never automated) | reason |
| `MemoryAccessed` | A consumer recalled it | context — retention-score input |

## Proposal events

`ProposalOpened` (carrying **draft intents**, not events — ADR-0018),
`ProposalApproved`, `ProposalRejected`, `ProposalMerged` (with the ids of the
aggregate-decided events appended in the same atomic batch), and `ProposalUndone`
(with the ids of the compensating events; ADR-0018 §3 — history is never rewritten).

Pipeline-opened proposals carry their full run explanation — provider, model ids,
prompt versions, seed, stage counts, scoring notes — as JSON in the opening
envelope's `Provenance.detail` (ADR-0019 §3). It is metadata: replayed verbatim,
folded by nothing.

### Forward compatibility (accepted extension)

Today the envelope carries `schema_version` (payload shape, upcast on read) and
`stream_seq` (the aggregate's version). A third field, **`minimum_reader_version`**, is
accepted-but-unimplemented: it will let a *newer* writer mark events that an *older*
reader must refuse to fold, instead of misinterpreting them. It lands the first time we
ship a change where old readers would be wrong rather than merely incomplete — per the
architecture freeze, not before. Until then, the aggregate's rule ("unknown event types
refuse to fold") is the backstop.

## Rules

1. **Names are facts**: `<Noun><PastTenseVerb>`. Never commands (`CreateMemory` ❌).
2. **Payloads never change shape in place.** Bump `schema_version` in `build_registry`,
   register an upcaster (vN dict → vN+1 dict). Historical logs must replay forever —
   the registry test (`test_registry_covers_every_event_dataclass`) plus upcaster
   coverage is the guardrail.
3. **Every emitted type is registered.** An event that can be written but not
   deserialized corrupts replay; CI enforces registry completeness.
4. **Corrections are compensating events.** The log is append-only at the SQLite trigger
   level, not just by convention.
5. **Provenance is mandatory.** A shared multi-assistant memory is only trustworthy if
   every fact knows who put it there.
