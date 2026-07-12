# ADR-0014: AI-affecting changes must meet or beat the committed baseline

- **Status**: Accepted
- **Date**: 2026-07-11

## Context

Almost every AI product regresses silently: someone "improves" a prompt or swaps a
model, it feels better on three examples, and quality quietly drops on the thousand
cases nobody re-ran. engram's extraction quality *is* the product — it needs the
discipline model labs apply internally: golden sets, scored runs, and a regression gate.

## Decision

- `evaluations/` exists from day 0: `golden/` (hand-curated cases: conversation →
  expected pipeline outcome), `synthetic/` (generated corpus with ground truth attached
  at generation time), `results/baseline.json` (the committed current scores).
- Harness contracts live in `engram_intelligence/evals.py` (`EvalCase`, `EvalScore`,
  `StageEvaluator`, regression gate). Scoring is per-stage *and* end-to-end, so a
  regression is localizable to the stage that caused it.
- **The gate**: any PR touching prompts, providers, pipeline stages, or scoring
  constants must run the golden suite; scores below `baseline.json` fail. Improvements
  update the committed baseline in the same PR — the baseline diff is the review
  evidence.
- Deterministic stages (chunking, validation, conflict rules) run in CI always. LLM
  stages run when a provider is configured (locally, or CI with a pinned local model);
  their baseline entries are marked with the provider+model used, since scores are only
  comparable within a configuration.
- Synthetic cases are generated **seeded**, committed by generator version + seed hash,
  not by content — reproducible without repository bloat.

## Consequences

- "Feels better" is replaced by a number that must not go down. ✔
- Regressions are caught at the stage level before users lose memories to them. ✔
- Golden curation is ongoing manual work — accepted; the golden set is as much the
  product spec as the docs are.
- LLM-stage scores drift with upstream model changes outside our control; mitigated by
  recording provider+model in the baseline and re-baselining explicitly when
  configurations change (never silently).

## Alternatives considered

- **Trust code review**: reviewers cannot see behavior across a corpus. Rejected.
- **LLM-as-judge only**: cheap but circular and unstable as the sole signal; acceptable
  later as *one* scorer among exact-match scorers on synthetic ground truth.
