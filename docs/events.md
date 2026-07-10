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

| Event | Emitted when | Payload highlights |
| --- | --- | --- |
| `MemoryCreated` | A memory is born | id, slug, title, content, type, tags |
| `MemoryEdited` | Content-level change | sparse fields (None = unchanged) |
| `MemoryEditedExternally` | Reconciler detected a direct file edit | changed fields + source path |
| `MemoryTagged` | Tags added/removed | added, removed |
| `MemoryLinked` / `MemoryUnlinked` | Graph edge change | target_id, relation |
| `MemoryMerged` | Another memory merged into this one | source_id, merged_content |
| `MemoryArchived` / `MemoryRestored` | Soft hide / unhide | reason |
| `MemoryDeleted` | Tombstone (log persists) | reason |
| `MemoryAccessed` | A consumer recalled it | context — feeds future decay |

## Proposal events

`ProposalOpened` (with serialized draft envelopes), `ProposalApproved`,
`ProposalRejected`, `ProposalMerged` (with the appended event ids).

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
