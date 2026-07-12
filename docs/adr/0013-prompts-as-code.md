# ADR-0013: Prompts are versioned, immutable, evaluated artifacts

- **Status**: Accepted
- **Date**: 2026-07-11

## Context

Prompts determine what engram remembers — they are the most behavior-critical text in
the system, and the industry default is to treat them as string literals edited in
place, unreviewed and unmeasured. A memory engine whose extraction behavior silently
changes between releases is untrustworthy.

## Decision

- Every prompt is a markdown file in `engram_intelligence/prompts/library/` with YAML
  frontmatter: `name`, `version`, `author`, `stage`, `expected_output`, `model_hints`.
  One file per version.
- **Shipped versions are immutable** — improving a prompt means a new version file. Old
  versions stay in the tree: past proposals reference them (`prompt_name@version` is
  recorded in proposal metadata), so they are part of the audit trail.
- The `PromptRegistry` mirrors the event/kind registries: registration, lookup by
  `(name, version)`, latest-version resolution. The orchestrator stamps the exact
  versions used into every proposal.
- Evaluation scores are **not** stored in the prompt file — they live in
  `evaluations/results/baseline.json`, derived, exactly like memory scores (ADR-0009).
- Review rules: a new prompt version requires (a) at least one golden case exercising
  it and (b) an eval run meeting the gate (ADR-0014). A prompt with no evaluation is
  dead code.

## Consequences

- Extraction behavior changes are diffable, reviewable, attributable, reversible. ✔
- "Why did engram remember this?" is answerable down to the prompt version. ✔
- Slight ceremony per prompt tweak — deliberate; prompt tweaks are behavior changes.

## Alternatives considered

- **Prompts as Python constants**: reviewable but tangles text with code, loses
  frontmatter metadata, and invites in-place edits.
- **Prompt-management SaaS / database**: runtime-mutable prompts are exactly the
  unauditable behavior drift this ADR exists to prevent, and violate local-first.
