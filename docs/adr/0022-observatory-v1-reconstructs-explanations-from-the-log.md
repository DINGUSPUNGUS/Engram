# ADR-0022: Observatory v1 reconstructs explanations from the log; the trace graph stays reserved

- **Status**: Accepted
- **Date**: 2026-08-05

## Context

M7 asks for the first explainability interface, built "using metadata that already
exists" and inventing none. Two candidate sources exist, and only one of them is real.

ADR-0015 reserved `libs/engram-observatory` and defined the eventual shape:
`DecisionTrace`, `TraceStep`, `TraceRecorder`, and an `ExplanationService` naming the
questions the system commits to answering. That package ships contracts only — every
`ExplanationService` method raises `NotImplementedError`, deliberately, so the
subsystems that make judgments are built emitting traces rather than retrofitted with
them. `InMemoryTraceRecorder` exists; nothing calls `record`.

Meanwhile ADR-0019 §3 put the pipeline's whole explanation somewhere durable and
shipped: `Provenance.detail` on the `ProposalOpened` envelope carries provider name,
`model_id`s, every `prompt@version`, seed/temperature, stage counts, scoring inputs and
timestamps as JSON — and asserts that "why does this memory exist?" is answerable from
the proposal's opening envelope alone.

So the Observatory can be built today from evented facts, or it can wait for a trace
subsystem that ADR-0015 says must not be built ahead of its emitters. Building it on
`ExplanationService` would mean implementing trace emission across scoring, conflict
detection, and the pipeline during a presentation milestone — expanding the frozen
architecture to satisfy a UI, with the tail wagging the dog.

## Decision

**1. Observatory v1 answers only from evented facts.**

Its sources are exactly:

- the memory's event history (`GET /memories/{id}/timeline`),
- the proposal's event history and lifecycle,
- `Provenance` on each envelope — `actor` is the originating assistant,
- `Provenance.detail` on `ProposalOpened` for provider, model, prompt versions,
  extraction stages and scoring decisions (ADR-0019 §3),
- `proposed_events` (draft intents) and `merged_event_ids` (merge provenance),
- the justification spine already on `MemoryResponse`: evidence, links, confidence.

**2. The Observatory does not call `ExplanationService`, and M7 does not implement
trace emission.** ADR-0015's build rule stands: traces land with the subsystems that
emit them, not with the screen that would display them.

**3. The scope limit is stated in the UI, not hidden.**

Reconstruction from the log answers: why this memory exists, where it came from, which
assistant proposed it, which evidence supports it, which proposal created it, why a
proposal was rejected (its `review_note` and rejecting actor), what changed after
replay, and how confidence moved (the spine records every mover).

It **cannot** answer "why was this *not* created" — ADR-0015 already identified why:
pipeline rejections and heuristic decisions never become events, so a candidate the
extractor dropped leaves no trace in the log. The Observatory says so plainly at that
seam and links to ADR-0015. It must never infer a reason it does not have.

**4. Absent or unparseable provenance degrades visibly.**

`Provenance.detail` is free-form and optional: hand-written CLI events have none, and
older events predate ADR-0019. The renderer parses JSON into a structured panel when it
can, shows the raw string verbatim when it cannot, and states "no pipeline provenance
recorded" when there is none. It never fabricates a provider, model, or prompt version,
and never guesses from surrounding events.

**5. The view contract is source-agnostic.**

The Observatory's read models are shaped around questions ("what produced this?"), not
around their current source. When trace emission lands, traces become an additional
source behind the same contract — an enrichment, not a rewrite, and not a v2 of the UI.

## Consequences

- The dashboard can answer the questions M7 names, today, with zero new domain
  concepts and zero new metadata. ✔
- Every answer is backed by an immutable, replayable event, so the explanation is as
  durable and as auditable as the state it explains. ✔
- The trace subsystem stays honestly unbuilt rather than half-built to serve a screen.
  ADR-0015's sequencing survives M7 intact. ✔
- The "why not?" gap is real and now visible to users. That is the correct trade:
  ADR-0015 predicted it, and a stated gap is worth more than a plausible guess.
- Explanation quality is bounded by what emitters wrote into `Provenance.detail`. If
  the orchestrator records a thin explanation, the Observatory shows a thin one — the
  UI cannot be better than its evidence, and should not pretend to be.
- Parsing free-form JSON at render time means the dashboard tolerates shapes it does
  not recognize. Unknown keys are displayed, not dropped, so a richer future
  explanation is visible before any UI work ships to support it.

## Alternatives considered

- **Implement `ExplanationService` now.** Requires trace emission across scoring,
  conflict detection, the pipeline and evals — a domain-wide change during a
  presentation milestone, and a direct violation of the freeze and of ADR-0015's build
  rule. Rejected.
- **Have the frontend assemble explanations from raw `/events`.** Puts reasoning
  reconstruction — a domain operation — into React components, which is the specific
  thing M7 forbids, and duplicates logic the CLI and MCP server would then lack.
  Rejected.
- **Persist a denormalized "explanation" record per memory at write time.** A sidecar
  audit trail split from the log it explains; ADR-0019 rejected this same shape for
  pipeline runs and the reasoning is unchanged — it dies in export/restore round-trips.
  Rejected.
- **Silently omit the "why not?" question from the UI.** The interface would look
  complete while being unable to answer one of the questions ADR-0015 commits to. An
  explainability surface that hides its own blind spot is worse than one that names it.
  Rejected.
