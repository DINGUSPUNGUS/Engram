# ADR-0015: Explainability is a subsystem — the observatory audit graph

- **Status**: Accepted
- **Date**: 2026-07-12

## Context

engram makes consequential judgments on the user's behalf: what to remember, what to
forget, what conflicts, what a confidence of 0.73 means. Logs answer "what happened";
users ask "**why** did it do that?" — "it remembered my old address but forgot my new
one" must be answerable with the exact reasoning chain, or trust is gone. This is also
where the product principle is recorded: **engram is boringly trustworthy** — not
flashy, not magical; predictable, explainable, reproducible, versioned, reversible.

## Decision

- A reserved package, `libs/engram-observatory`, holding the **audit graph**: not
  logging, but structured `DecisionTrace`s — one answered question about one subject
  (memory, proposal, evaluation, pipeline run) as an ordered chain of `TraceStep`s
  (rule fired · heuristic · prompt@version + model_id · evidence · score · decision).
- The `TraceRecorder` port is append-only (traces are evidence); the
  `ExplanationService` contract names the questions the system commits to answering:
  why created, why *not* created, why this confidence, why a duplicate, why an
  evaluation failed.
- Layering: observatory sits between core and the adapter layer, so intelligence,
  storage, and the eval harness may all *emit* traces, while core stays unaware of it.
- **Build rule**: subsystems that make judgments (pipeline stages, conflict rules,
  scoring, evals) are implemented *emitting traces from day one* — explainability is
  not retrofittable. Existing sources of "why" (the event log, prompt versions,
  scoring inputs) are referenced by traces, never duplicated into them.

## Consequences

- "Why?" has a reconstructable answer at every level, which is the difference between
  a memory tool and memory infrastructure people trust. ✔
- Each judgment-making subsystem carries a small trace-emission cost — deliberate;
  a judgment too expensive to explain is a judgment engram shouldn't make.
- Trace storage/retention policy is deferred until the first emitter lands (traces
  about derived scores are themselves derivable; traces about LLM outputs are not).

## Alternatives considered

- **Structured logging + correlation ids**: answers "what", drowns "why" in noise,
  and log retention policies eventually eat the evidence.
- **Reconstruct explanations purely from the event log**: works for event-sourced
  state, but pipeline rejections and heuristic decisions never become events — the
  "why not" questions would be unanswerable.
