# ADR-0019: Scoring resolves at decide time; confidence compensates through a restoration event; pipeline runs are provenance

- **Status**: Accepted
- **Date**: 2026-07-15

## Context

M5 activates the last dormant parts of the justification spine: `MemoryConfirmed`,
`MemoryContradicted`, and `MemoryImportanceAdjusted` gain emitters, and the
intelligence pipeline starts opening proposals whose outputs must be explainable
years later. Three decisions are not covered by existing ADRs:

1. **Where does the confirmation/contradiction weight come from, and what does the
   event record?** ADR-0009 fixes the split (signals evented, scores derived) and
   memory-model.md §5 fixes the formulas (`c' = c + (1−c)·w`, `c' = c·(1−w)`), but
   not whether `w` lives in the event, in fold-time config, or in both.
2. **How does undo compensate a confidence movement?** ADR-0018 demands one inverse
   event per merged event, but no existing event can restore `confidence` *and*
   `last_confirmed_at` to prior values — a compensating "confirm" would falsely
   reset the staleness clock; a compensating "contradict" cannot raise confidence.
3. **Where does a pipeline run's explanation live?** The observability contract
   (source input, stages, provider, model, prompt versions, scoring decisions,
   configuration) must survive forever without affecting replay semantics.

## Decision

### 1. Weights resolve at decide time and are recorded in the event

`decide_confirm` / `decide_contradict` take an explicit `weight`; the command
services resolve it from the scoring policy (`engram_core/domain/scoring.py`) and
the caller's provenance (user > assistant) *before* deciding, and the resolved
weight is stored in the event payload. Fold applies the §5 formula using the stored
weight — replay is a pure function of the log, unaffected by later policy tuning.

This follows the existing precedent exactly: `MemoryCreated` already stores the
resolved confidence prior (0.95 for user-stated), not a pointer to the policy that
produced it. The *signal and its resolved magnitude* are facts of the decision;
only *derived* scores (effective confidence, retention) stay out of the log.

Confirms/contradicts merged **through a proposal** always use the assistant-class
weight: proposals are automation's door (ADR-0011), and the human approval reviews
the claim, it does not become the claimant. Direct CLI commands use the invoking
actor's weight.

The three payloads gain fields (`weight`; `clear_user_weight` on importance) at
`schema_version 1` without an upcaster: no emitter has ever existed, so no log can
contain these event types. This is the only time that is true — from M5 on, these
shapes are shipped and immutable (ADR-0002 rules apply).

### 2. `MemoryConfidenceRestored` — the confidence compensator

A new event, emitted **only by proposal undo** (the `MemoryEvidenceRetracted`
precedent from ADR-0018): it restores `confidence` and `last_confirmed_at` to
explicitly recorded prior values. Undo of a merged `MemoryConfirmed` or
`MemoryContradicted` appends one. It is not a command anyone can issue — there is
no `decide_*` for it — so confidence still has exactly three movers (confirmation,
contradiction, time) plus the undo of the first two.

### 3. Pipeline provenance rides `Provenance.detail`

The orchestrator serializes the run's explanation — provider name, opaque
`model_id`s, every `prompt@version`, seed/temperature, stage counts, scoring
inputs, timestamps — as JSON into `Provenance.detail` on the `ProposalOpened`
envelope (the field designed for "free-form context"), and mirrors the
human-readable summary into the proposal description. It is envelope metadata:
replayed byte-for-byte, folded by nothing, branching nothing. Determinism contract:
given identical provider/model/prompt/input/configuration the pipeline produces
identical *intents* (memory ids are freshly minted UUIDv7 — identity is never
derived from content, ADR-0003); provider nondeterminism is confined behind the
port and pinned where the provider allows (Ollama: `seed` + `temperature 0`).

## Consequences

- Old events replay identically forever, however often weights are re-tuned —
  tuning changes future decisions only. ✔
- Undo restores confidence state exactly, without fabricating a vouching. ✔
- "Why does this memory exist?" is answerable from the proposal's opening envelope
  alone: input, prompts, model, scores. ✔
- Cost: weight constants are duplicated into history (by design — history must not
  re-interpret), and one more undo-only event type exists.

## Alternatives considered

- **Fold-time weights from config**: replay state would change whenever policy
  changes — replay determinism broken by a config edit. Rejected.
- **Store `confidence_after` instead of `weight`**: replays identically, but
  records a conclusion instead of a signal and makes the formula unauditable.
  The weight *is* the signal's magnitude; the result is derivable. Rejected.
- **Compensate confirm with contradict (and vice versa)**: cannot restore
  `last_confirmed_at`; muddies "who vouched" semantics with technical inversions.
  Rejected.
- **A sidecar metadata table for pipeline runs**: splits the audit trail from the
  log it explains and dies in export/restore round-trips. `Provenance.detail`
  travels with the event everywhere the event goes. Rejected.
