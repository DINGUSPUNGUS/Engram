# ADR-0010: Two-tier graph — lightweight typed edges plus reified relationships

- **Status**: Accepted
- **Date**: 2026-07-11

## Context

The knowledge graph must support both cheap structural links ("this note is about that
project") and knowledge-bearing connections ("Alice manages Bob since 2024, per the
standup transcript") — the latter needs confidence, evidence, lifetime, and history of
its own. One mechanism serving both either bloats every link or starves the rich ones.

## Decision

- **Tier 1 — edges** (`Link` value on the source memory, `MemoryLinked` events,
  `links` projection): directed, typed from a closed core vocabulary (`about`,
  `involves`, `part_of`, `owned_by`, `works_at`, `located_in`, `relates_to`,
  `supersedes`, `derived_from`, `contradicts`). Only the canonical direction is stored;
  inverse names are query-time aliases. Kind schemas declare which relations they may
  emit. Extending the vocabulary requires an ADR.
- **Tier 2 — reified relationships** (kind = `relationship` with `subject_id`,
  `predicate`, `object_id`, `since`, `until`): full memory objects with the complete
  justification spine. Rule of thumb: if the connection could ever need confirming,
  contradicting, or dating — reify it.
- **Integrity**: no cascading deletes; edges may dangle when targets are merged or
  archived (traversal skips, a maintenance projection reports). Merges re-point edges to
  the survivor. Link degree feeds retention-score centrality.

## Consequences

- 95% of links stay one-row cheap; the 5% that are knowledge get the full spine. ✔
- Closed vocabulary keeps traversal queries writable by hand and by LLMs. ✔
- Two ways to express a connection demands a documented rule of thumb (in the model doc
  and CONTRIBUTING) — accepted cost of not over- or under-modeling.

## Alternatives considered

- **Everything reified**: every "about" becomes a three-stream write; absurd overhead.
- **Everything lightweight**: relationship knowledge gets no evidence/confidence — fails
  the justification-spine principle.
- **Open (free-text) relation vocabulary**: unqueryable graph within months.
