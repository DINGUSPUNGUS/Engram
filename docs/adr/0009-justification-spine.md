# ADR-0009: The justification spine — signals are events, scores are projections

- **Status**: Accepted
- **Date**: 2026-07-11

## Context

Every memory must answer *"why does this deserve to exist?"* — the backbone of automatic
pruning. That requires per-memory confidence, evidence, importance, lifetime, and
visibility. The design question: which of these are *recorded facts* and which are
*computed opinions*?

## Decision

Split hard along that line:

- **Recorded in the event log (facts):** source provenance, evidence refs (append-only),
  confirmations (`MemoryConfirmed`), contradictions (`MemoryContradicted`), accesses
  (`MemoryAccessed`), pins and explicit user weights (`MemoryImportanceAdjusted`),
  lifetime and visibility changes.
- **Derived in projections (opinions):** effective confidence (stored confidence × time
  decay), importance score, retention score, staleness. Formulas and constants live in
  one tunable config module; recomputing the whole corpus is `engram rebuild`, not a
  migration.

Spine fields on every memory: `source`, `evidence[]`, `confidence`, `last_confirmed_at`,
`importance` signals, `lifetime` (permanent · standard · until · ephemeral), `visibility`
(private · shared · restricted). Enforcement point for visibility is the query/recall
boundary.

## Consequences

- Decay/importance formulas can be tuned forever without corrupting history — the log
  never contains a number an algorithm made up. ✔
- Retroactive scoring works: `MemoryAccessed` events from day 1 mean the M5 decay
  model applies to the entire corpus the moment it ships. ✔
- Confidence has exactly three movers: confirmation events, contradiction events, and
  time. No silent writes. ✔
- Cost: projections must be recomputed when constants change (cheap at this scale, and
  already required by the rebuild contract).

## Alternatives considered

- **Store computed scores in the log**: every tuning pass becomes a data migration and
  history fills with algorithmic noise. Rejected.
- **No confidence scalar, full belief revision (evidence-weighted truth maintenance)**:
  intellectually attractive, operationally unjustifiable complexity for this product.
