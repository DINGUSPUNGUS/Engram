---
id: preference_002
scenario: conflicting-preferences
stages: [evidence_extraction, candidate_generation, conflict_detection]
---

## Conversation

USER: For the dashboard, I actually prefer dark mode as the default now. I know I said
light mode before, but I've changed my mind.
ASSISTANT: Understood — dark mode as the default going forward.
USER: For print stylesheets keep everything light though, obviously.

## Expected

```yaml
# Assumes an existing preference memory (prefers light mode, context: dashboard)
# is present in the fixture state.
candidates:
  - kind: preference
    attributes: { polarity: prefers, context: "dashboard theme" }
    content_mentions: "dark mode"
  - kind: preference
    attributes: { polarity: prefers, context: "print stylesheets" }
    content_mentions: "light"
conflicts:
  - conflict_class: contradiction
    detail: "same context (dashboard theme) as the existing light-mode preference — expect supersede, user explicitly revoked"
coexistence:
  - "print stylesheet preference must NOT conflict — different context (memory-model.md §8)"
```
