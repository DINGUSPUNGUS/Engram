# Evaluations

**The gate that keeps engram's AI honest (ADR-0014): no AI-affecting change merges
below the committed baseline.** Design of record: [docs/intelligence.md](../docs/intelligence.md) §4–5.

## Layout

| Path | What it is |
| --- | --- |
| `golden/` | Hand-curated cases: conversation → expected pipeline outcome. Small, high-precision — this set is as much the product spec as the docs are. |
| `synthetic/` | Scenario taxonomy + generated corpus (seeded, committed by generator version + seed hash). Scale testing with exact ground truth. |
| `results/baseline.json` | The committed current scores, per stage and end-to-end. The number that must not go down. |

## Golden case format

One markdown file per case:

```markdown
---
id: person_001
scenario: duplicate-contacts
stages: [evidence_extraction, entity_resolution, conflict_detection]
---

## Conversation

USER: My colleague Sarah Chen — sarah@acme.io — is joining the project.
ASSISTANT: Noted...

## Expected

​```yaml
candidates:
  - kind: person
    attributes: { full_name: "Sarah Chen" }
  - kind: contact
    attributes: { channel: email, value: "sarah@acme.io" }
    links: [{ relation: owned_by, target: candidate:0 }]
conflicts: []
​```
```

A case may declare fixture state in its Expected YAML under `existing:` — memories
the harness seeds before evaluating resolution/conflict stages (deterministic ids,
`uuid5(case, index)`).

## Running (live since M5)

- Deterministic stages (chunking, entity resolution, conflict rules) run in CI on
  every PR: `test_golden_gate.py` executes `deterministic_evaluators()` over
  `golden/` and enforces `results/baseline.json` via `check_regression`.
- LLM-backed stages (`evidence_extraction`, `candidate_generation`) have evaluators
  in `engram_intelligence.evaluators`; run them locally against a configured
  provider. Scores are only comparable within one provider+model configuration,
  which the baseline records — they enter the committed baseline the first time a
  configuration is pinned.
- The gate: `check_regression(baseline, current)` — regressed stages fail the PR.
  Improvements update `results/baseline.json` **in the same PR**; the baseline diff is
  the review evidence.

## Rules

1. Every prompt version has at least one golden case exercising it (ADR-0013).
2. A new failure mode found in the wild becomes a golden case before it is fixed.
3. Baselines are re-anchored explicitly (own commit, own reasoning) when the provider
   or model configuration changes — never silently.
