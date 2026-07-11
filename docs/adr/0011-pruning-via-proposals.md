# ADR-0011: Pruning proposes; humans (or explicit policy) decide

- **Status**: Accepted
- **Date**: 2026-07-11

## Context

Automatic pruning is the point of the justification spine — a memory that can't say why
it deserves to exist should go. But a memory system that silently discards things it
deems unimportant destroys the one property that makes it trustworthy. The user must
never wonder what the machine forgot on their behalf.

## Decision

- Decay computes `retention_score` for unpinned, non-permanent memories (formula and
  half-lives in the model doc §7; constants in one tunable module).
- Below-threshold memories are batched into an **archive Proposal** whose description
  carries the scores and reasons — pruning produces *evidence*, not deletions.
- Merging the proposal appends ordinary `MemoryArchived` events. The log records exactly
  why every memory was archived, forever. Restore is one event.
- Auto-approval is possible but only as an **explicit, per-space, opt-in policy** (e.g.
  "auto-archive ephemeral episodic events older than 90 days"). Default: human review.
- Hard rules: pinned and `lifetime=permanent` memories are never proposed; tombstoning
  (`MemoryDeleted`) is never automated, full stop.

## Consequences

- Pruning is as auditable and reversible as creation — the trust property holds. ✔
- Reuses the existing Proposal machinery instead of a parallel "cleanup" system. ✔
- A neglected review queue can grow; mitigated by the opt-in auto-policies and by
  down-ranking stale memories in recall regardless of archival state.

## Alternatives considered

- **Silent auto-archive**: maximally convenient, fatally corrosive to trust. Rejected.
- **Never prune, only down-rank**: recall quality survives, but the corpus (and the
  user's export repo) grows unbounded with noise. Down-ranking is the *first* line;
  proposals are the second.
