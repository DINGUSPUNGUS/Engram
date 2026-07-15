# The Export Format

**Status: the M3 document of record.** How an engram space becomes a portable,
human-editable repository — and how it comes back. The role of each layer is decided
in [ADR-0017](adr/0017-portability-layers.md); this document specifies the bytes.

The contract, in one line: **export is deterministic, import is validated, the
round-trip is lossless** (via the event log), and nothing imported bypasses proposals.

## 1. Repository layout

```
<export-repo>/
├── README.md                  # generated; explains the repo to humans
├── manifest.json              # integrity: counts, checksums, merkle root
├── memory/                    # the human face — one file per memory
│   ├── facts/…  preferences/…  people/…  organizations/…  projects/…
│   ├── skills/…  goals/…  contacts/…  events/…  locations/…  assets/…
│   └── relationships/         # reified relationship objects, explicit files
├── timeline/
│   └── events.ndjson          # the complete event log — the restore path
└── metadata/
    └── memories.ndjson        # current state for foreign systems (bulk interchange)
```

Filenames derive from mutable slugs (`memory/<kind-plural>/<slug>.md`); **identity
lives in frontmatter** (ADR-0003). A rename changes the filename; the `id` never
changes. The exporter owns these lanes and nothing else: it will create, rewrite, and
delete files inside them, and never touches anything outside them.

## 2. Markdown documents

Every memory exports as YAML frontmatter + narrative body + a machine-managed
evidence section:

```markdown
---
id: "019f5629-6a31-7f50-a869-10d56882d5e8"
kind: "fact"
schema_version: 1
title: "User prefers dark mode"
slug: "user-prefers-dark-mode-019f5629"
created_at: "2026-07-12T10:15:37.123456Z"
updated_at: "2026-07-12T10:15:37.123456Z"
created_by: "user"
confidence: 0.95
visibility: "shared"
lifetime: "standard"
tags:
  - "ui"
links:
  - relation: "about"
    target: "019f5629-6009-739c-a5c9-c83c2d8f2c5d"
attributes:
  statement: "User prefers dark mode"
---

always dark themes

## Evidence

```yaml
- type: "quote"
  value: "let's always use dark mode"
  added_at: "2026-07-12T10:16:02.000001Z"
  actor: "user"
```
```

Rules:

- **Key order is fixed** (`id, kind, schema_version, title, slug, created_at,
  updated_at, created_by, confidence, visibility, lifetime[, lifetime_until][,
  archived][, pinned][, user_weight], tags, links, attributes`). Optional keys are
  omitted when at their default — a memory that was never archived shows no
  `archived:` line.
- **Rendering is hand-written, not a YAML library**: strings are JSON string
  literals (JSON ⊂ YAML), timestamps are ISO-8601 UTC with `Z`, tags sorted,
  links sorted by `(relation, target)`, attribute keys sorted, `None` attributes
  omitted. Same state ⇒ same bytes, forever.
- **Parsing is a YAML library** (`yaml.safe_load`): humans edit these files, and any
  YAML that *means* the same thing must import the same way.
- The trailing `## Evidence` section (fenced YAML list) is machine-managed spine
  data — append-only in engram, so edits there are surfaced during import validation
  rather than silently merged.
- Relationship **objects** (the reified twelfth kind) are ordinary documents under
  `memory/relationships/`; tier-1 **edges** are the `links:` list. Both survive
  round-trips.
- Derived scores (effective confidence, staleness) are **never exported** — they are
  functions of *now* (ADR-0009). `confidence` is the stored input.

## 3. NDJSON

Two files, each one JSON object per line, **sorted keys, compact separators,
UTF-8, `\n` line endings**, each record carrying `record_schema_version`:

- `timeline/events.ndjson` — every envelope, ordered by `global_seq`:
  `event_id`, `stream_id`, `stream_seq`, `event_type`, `schema_version`,
  `occurred_at`, `provenance{actor, session_id, detail}`, `payload{…}`.
  Payload values use the kernel's canonical JSON encodings (UUID → string,
  datetime → ISO-8601 `Z`). This file **is** the space: it replays.
- `metadata/memories.ndjson` — current state, ordered by `id`, designed for bulk
  import into other systems (no engram required to consume it).

## 4. Manifest & checksums

`manifest.json` (stable JSON, indent 2, sorted keys):

| Field | Meaning |
| --- | --- |
| `manifest_schema_version` | version of this manifest format; importers refuse newer |
| `export_format_version` | version of the layout/document formats |
| `engine_version` / `engine_git_commit` | what produced the export (commit is best-effort, may be null) |
| `generated_at` / `duration_ms` | volatile metadata — see determinism rule |
| `head_global_seq` | last exported event; drives `--incremental` |
| `counts` | `memories`, `links`, `relationship_objects`, `events` |
| `files` | relpath → sha256 of every content file |
| `merkle_root` | digest over the sorted `path digest` lines — two exports are equivalent iff roots match; future sync diffs against this |

**Determinism rule**: content files are byte-identical for identical state, and the
manifest is rewritten *only when content changed* — so a repeated no-change export
touches nothing at all (`generated_at`/`duration_ms` are frozen with it).

## 5. Restore vs import (two trust models)

- **`engram import --restore <repo|events.ndjson>`** reconstitutes the event log
  verbatim into an **empty** space (checksum-verified against the manifest,
  stream/global ordering validated), then rebuilds projections. This is disaster
  recovery / machine migration: those events were already decided once, so no
  proposals are involved — and it *refuses to run* on a non-empty space.
- **`engram import <path>`** treats markdown or `memories.ndjson` as candidate
  knowledge: every document is validated (kind schema via the KindRegistry, UUIDs,
  link relations + targets, evidence vocabulary, timestamps, confidence range) with
  **all problems reported at once and nothing written on failure**; success opens
  **one Proposal** carrying draft *intents* (ADR-0018). A document whose `id`
  already exists is **reconciled**: the current aggregate is folded from its
  stream, the semantic difference computed, and edit intents proposed — never a
  duplicate `MemoryCreated`; unchanged documents open nothing. Keys absent from a
  document are not diffed (a partial hand-written file is not a removal request);
  evidence removals are ignored (retraction is a reviewed undo, not a file edit);
  documents for deleted memories are rejected. Nothing imported bypasses the
  proposal system (ADR-0011): review with `engram proposals show`, then
  `approve` + `merge` (aggregate-validated, conflict-checked, atomic), and
  `undo` compensates a merge without ever rewriting history.

## 6. Git

`engram git init|status|commit` version the export repository. Git is a **consumer
of exported state** (ADR-0017): `commit` runs an export first, then commits; no git
operation ever mutates the runtime database. Cloning the repo elsewhere +
`engram init` + `engram import --restore` is the full portability story.

## 7. Versioning & compatibility

Three independent version axes, all embedded in the artifacts:

1. event `schema_version` (per payload; upcasters migrate on read — ADR-0002),
2. NDJSON `record_schema_version` (per record type),
3. `manifest_schema_version` / `export_format_version` (per export).

An importer accepts anything ≤ its own version and refuses anything newer with an
explicit "upgrade engram" error — old exports import forever; new exports never
corrupt old engines silently.
