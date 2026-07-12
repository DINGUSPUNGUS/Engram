# Intelligence Architecture

**Status: the Phase 0.75 deliverable.** How AI enters engram — and, more importantly, the
walls that keep it honest. Companion decisions:
[ADR-0012](adr/0012-llm-provider-abstraction.md) (providers are adapters; the core never
knows a model exists), [ADR-0013](adr/0013-prompts-as-code.md) (prompts are versioned
artifacts), [ADR-0014](adr/0014-evaluation-gate.md) (AI changes must beat the baseline).

The prime directive, inherited from ADR-0011: **AI proposes; events decide.** No pipeline
stage, no model, no score ever writes to a memory stream directly. The pipeline's single
terminal output is a Proposal. Everything downstream of human (or explicitly-configured
policy) approval is the ordinary event machinery.

## 1. The memory ingestion pipeline

Nine stages, each a port (Protocol) in `libs/engram-intelligence/pipeline/stages.py`,
each independently replaceable, testable against golden data, and benchmarkable:

```
Conversation transcript
   │ 1. Chunker              — split turns into semantically coherent chunks
   ▼
Chunks
   │ 2. EvidenceExtractor    — pull candidate quotes worth remembering  [LLM]
   ▼
Extracted evidence
   │ 3. EntityResolver       — resolve mentions against existing person/org/
   ▼                            location/asset memories (alias sets)     [LLM + search]
Resolved mentions
   │ 4. CandidateGenerator   — draft typed MemoryCandidates: kind, attributes
   ▼                            (validated against the KindRegistry), links [LLM]
Memory candidates
   │ 5. ConflictDetector     — duplicates & contradictions vs. current state
   ▼                            (memory-model.md §8 classes)             [search + LLM]
Conflict-annotated candidates
   │ 6. ImportanceScorer     — importance/confidence priors per candidate
   ▼                            (scoring.py constants; heuristics first, LLM later)
Scored candidates
   │ 7. ProposalAssembler    — bundle into ONE reviewable Proposal: creates,
   ▼                            edits, links, merges, contradiction flags
Proposal (draft events + evidence)
   │ 8. Human approval       — the existing Proposal review flow (ADR-0011)
   ▼
   9. Commit                 — ProposalCommandService.merge_proposal; ordinary events
```

Design rules:

- **Stage boundaries are data, not calls**: each stage consumes and produces frozen
  dataclasses (`pipeline/types.py`). Any stage can be swapped for a better model, a
  heuristic, or a human — the neighbors cannot tell.
- **Candidates are born justified**: evidence quotes attach at stage 2 and travel through
  every stage, so a merged proposal produces memories whose spine (source, evidence,
  confidence prior) is filled from birth.
- **Attribute validation happens inside the pipeline** (stage 4, via the KindRegistry) —
  a candidate that doesn't satisfy its kind schema never reaches review.
- **Provenance is pipeline-wide**: the transcript's assistant/session flows into every
  proposed event, so extraction is as auditable as manual writes.
- **The pipeline is resumable and stateless between stages** — orchestration state lives
  in the orchestrator, not in stages, so partial re-runs (e.g. re-score without
  re-extract) are natural.

## 2. LLM provider abstraction (ADR-0012)

```
engram-core          — does not know LLMs exist. No provider port here, ever.
engram-intelligence  — defines LLMProvider (Protocol) + request/response DTOs
  providers/claude   — Anthropic SDK confined here
  providers/openai   — OpenAI SDK confined here
  providers/gemini   — Google SDK confined here
  providers/ollama   — local HTTP; the local-first default
```

The port (`provider.py`) is deliberately minimal: `complete(LLMRequest) -> LLMResponse`,
a `name` for provenance, and capability flags (`supports_structured_output`). Requests
carry the *rendered* prompt plus the prompt's name/version (for audit); responses carry
text, token usage, latency, and an opaque `model_id` recorded for provenance only —
**nothing in engram may branch on which model produced an output.** Import-linter
enforces the wall: `engram_core` cannot import `engram_intelligence`; SDKs never appear
outside `providers/`.

Provider selection is configuration (`ENGRAM_LLM_PROVIDER`, per-stage overrides later),
resolved at the composition root like every other adapter. Ollama is the default: the
pipeline must be fully functional with zero cloud dependencies.

## 3. Prompts are code (ADR-0013)

Every prompt is a versioned artifact in `libs/engram-intelligence/src/engram_intelligence/
prompts/library/`, one markdown file per version, YAML frontmatter + body:

```markdown
---
name: evidence-extraction
version: 1
author: engram-core-team
stage: evidence_extraction
expected_output: JSON array of {quote, evidence_type, reason} objects
model_hints: [json-output]
---
You are extracting durable facts from a conversation…
```

Rules, mirroring the event/kind registries:

- The `PromptRegistry` loads the library and serves `(name, version)`; the orchestrator
  records the exact prompt version in every proposal's metadata — outputs are
  reproducible and attributable.
- **Shipped prompt versions are immutable.** Improving a prompt = a new version file;
  old versions stay in the tree (they are part of the audit trail of past proposals).
- A prompt version's *evaluation score* is not stored in the file — it lives in
  `evaluations/results/baseline.json`, computed, exactly like memory scores (ADR-0009
  thinking applied to prompts).
- Every prompt has at least one golden case exercising it. A prompt with no evaluation
  is dead code and fails review.

## 4. Evaluations (ADR-0014)

Where AI projects die is unmeasured "improvements". The gate exists from day 0:

```
evaluations/
├── README.md           # methodology + how to run + how the gate works
├── golden/             # hand-curated cases: input conversation → expected proposals
│   ├── person_001.md
│   ├── project_017.md
│   └── preference_002.md
├── synthetic/          # generated corpus (see §5): scenarios.md + generated/
└── results/
    └── baseline.json   # committed current scores per stage + end-to-end
```

- A **golden case** is a markdown file: frontmatter (id, scenario, stages under test),
  the conversation, and the expected outcome (candidates/conflicts/proposal shape) as a
  fenced YAML block. Human-curated, small (dozens), high-precision.
- The harness contracts live in `engram_intelligence/evals.py`: `EvalCase`,
  `EvalScore`, `StageEvaluator` (Protocol), and the regression gate. Scoring is
  per-stage (chunking F1, extraction precision/recall, resolution accuracy, conflict
  detection precision, end-to-end proposal quality).
- **The gate: no AI-affecting change merges below baseline.** CI runs the golden suite
  (deterministic stages always; LLM stages when a provider is configured) and compares
  against `results/baseline.json`. Improving the baseline updates the committed file in
  the same PR — the diff *is* the evidence.

## 5. Synthetic test corpus

Golden sets measure precision; the synthetic corpus measures behavior at scale.
`evaluations/synthetic/scenarios.md` defines the taxonomy; a generator (milestone M5,
contract in `evals.py`) produces thousands of fake conversations per scenario,
with ground truth attached at generation time — so scoring is exact, not judged:

| Scenario family | What it stresses |
| --- | --- |
| Conflicting preferences (same/different context) | ConflictDetector, coexist-vs-supersede |
| Duplicate contacts / renamed people | EntityResolver, merge proposals |
| Renamed businesses, rebrands | Alias sets, `supersedes` edges |
| Job changes over time | `works_at` edge lifecycle, contradiction handling |
| Contradictory facts, later corrections | Confidence math, contradiction queue |
| Long-running projects across many sessions | Cross-session entity resolution, `about` linking |
| Noise: small talk, jokes, hypotheticals | Extraction precision (what NOT to remember) |
| Adversarial: prompt-injection in conversation | Pipeline treats content as data (security.md) |

Generated conversations are seeded and committed by hash, not by content — reproducible
without bloating the repo.

## 6. What Phase 0.75 deliberately does not do

- No LLM calls, no SDK dependencies, no extraction logic — contracts, types, formats,
  and the eval gate only. Implementation is milestone M5, and it lands stage by
  stage against these interfaces.
- No streaming/agentic pipeline steps: `complete()` request/response is enough for
  every stage; revisit only with evidence.
- No auto-approval of extraction proposals — that policy question stays with ADR-0011.
