# ADR-0012: LLM providers are adapters; the core never knows a model exists

- **Status**: Accepted
- **Date**: 2026-07-11

## Context

engram's mission is one memory shared by *every* assistant — ChatGPT, Claude, Gemini,
Cursor, local Ollama models. A memory engine that hard-codes one vendor's SDK into its
heart has already failed that mission; worse, model choice churns every few months while
this codebase is designed for a decade.

## Decision

- A single port, `LLMProvider` (`engram_intelligence/provider.py`): `complete(LLMRequest)
  -> LLMResponse`, a `name`, and capability flags. Requests carry rendered prompts plus
  prompt name/version for audit; responses carry text, usage, latency, and an opaque
  `model_id` recorded for provenance only.
- The port lives in **engram-intelligence, not engram-core**. The domain layer does not
  know LLMs exist; the pipeline's only output is a Proposal, which enters through the
  same door as every other write. Import-linter enforces it: core cannot import
  intelligence.
- Vendor SDKs are confined to `engram_intelligence/providers/<vendor>.py`. Nothing else
  in the repository may import them — including the rest of engram-intelligence.
- **No behavior may branch on `model_id`.** If a stage needs a capability, it asks the
  port's capability flags, never the vendor name.
- Provider selection is configuration (`ENGRAM_LLM_PROVIDER`), resolved at composition
  roots. **Ollama is the reference default**: every pipeline stage must be fully
  functional with zero cloud dependencies, or engram is not local-first.

## Consequences

- Model churn becomes a config change; new vendors are one adapter file. ✔
- Stages are testable with a `FakeProvider` returning canned responses. ✔
- The lowest-common-denominator port (`complete()`) forgoes vendor-specific features
  (caching hints, native tool use). Accepted: capability flags are the escape valve,
  and any richer contract must be added to the *port*, never side-channeled.

## Alternatives considered

- **Port in engram-core** (like `EmbeddingProvider`): tempting symmetry, but embeddings
  are a storage concern the domain legitimately owns an interface for; conversational
  LLM use is an ingestion concern with no domain invariants. Keeping it out of core
  keeps "AI proposes, events decide" structural.
- **LangChain/LiteLLM as the abstraction**: imports the churn we're isolating against
  into the foundation. A 30-line Protocol we own outlives any framework.
