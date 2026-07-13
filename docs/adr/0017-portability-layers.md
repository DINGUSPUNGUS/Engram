# ADR-0017: The portability layers — who is canonical for what

- **Status**: accepted (2026-07-13)
- **Deciders**: project owner, M3 implementation
- **Refines**: ADR-0001 (three-layer storage), ADR-0011 (proposals)

## Context

M3 makes engram portable. That forces precision about a question ADR-0001 answered
only loosely: when four representations of the same memory exist (event log, SQLite
tables, markdown files, git history), which one wins, when, and why? Every sync bug
in every dual-representation system ever shipped comes from answering this vaguely.

## Decision

One directed chain, no cycles:

| Layer | Role | May be regenerated from |
| --- | --- | --- |
| **Event log** | **Source of truth.** The only thing that *is* the space. Append-only, replayable, exported verbatim as `timeline/events.ndjson`. | nothing — it is the origin |
| **SQLite projections** | **Runtime projection.** Disposable, rebuilt by replay (`engram rebuild`). Exists because queries are database problems. | the event log |
| **Markdown** | **Canonical interchange format.** The human-readable, human-*editable*, tool-agnostic face. What other systems and future selves read. | the projections (deterministically) |
| **Git** | **Versioned distribution layer.** Transport, history, and diffing for the exported tree. Consumes exports; never produces state. | the working tree |

Data flows **down** that table freely and deterministically. Data flows **up** only
through two guarded doors:

1. **Restore** (`import --restore`): the exported event log reconstitutes an *empty*
   space verbatim. Not an import — those events were already decided once; replaying
   them is migration/disaster recovery. It refuses non-empty spaces, so it can never
   merge, overwrite, or race anything.
2. **Import** (everything else): markdown or NDJSON documents are *candidate
   knowledge* — validated exhaustively, then wrapped in a **Proposal**. Nothing
   imported bypasses the proposal system; a human approves and merges (M4). This is
   ADR-0011 applied to files: an edited markdown file is exactly as untrusted as an
   LLM extraction.

Two supporting rules make the chain safe to operate:

- **Determinism**: identical state ⇒ byte-identical export (fixed key orders,
  hand-rendered YAML, sorted NDJSON keys, canonical value encodings in the kernel's
  serde). The manifest's volatile fields are only refreshed when content changes, so
  a no-change export touches nothing and produces no git noise.
- **Integrity**: every exported file is checksummed; the manifest carries a
  Merkle-style root. Restore verifies the event log's checksum before replaying;
  future sync diffs roots instead of trees.

## Consequences

- "Lossless round-trip" has a precise meaning: export → empty machine → restore →
  rebuild ⇒ identical events (ids, payloads, provenance, order) and therefore
  identical projected state — CI-tested as the M3 invariant.
- Markdown round-trips *content* faithfully but is not the history: a markdown-only
  copy of a space loses timelines by construction. The events file exists precisely
  so nobody is ever tempted to reconstruct history from prose.
- Git operations can be run by anything (hooks, cron, CI) with zero risk to runtime
  state — the port only sees the export directory.
- The reconciler (detecting external markdown edits and turning them into targeted
  `MemoryEditedExternally` drafts, rather than whole-memory imports) remains future
  work; until then, edited exports re-enter through import-as-proposal.

## Alternatives rejected

1. **Git-canonical** (state lives in files; DB is a cache) — rejected in ADR-0001 and
   the rejection survives M3: merge semantics for structured knowledge in text files
   are a research project, not a foundation.
2. **Bidirectional sync without proposals** — every edit anywhere merges everywhere;
   rejected: silent conflict resolution is the opposite of "boringly trustworthy".
3. **Restore-through-proposals** — importing history as drafts to approve; rejected:
   a proposal produces *new* events with new identity, so history (event ids,
   provenance, order) could never survive, breaking the round-trip guarantee the
   milestone exists to prove.
