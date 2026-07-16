---
id: project_017
scenario: long-running-project
stages: [evidence_extraction, entity_resolution, candidate_generation, conflict_detection]
---

## Conversation

USER: Status update on engram: we finished the architecture phase, so I'm flipping it
from idea to active. Target for the first usable build is end of September.
ASSISTANT: Congrats! So engram is now an active project with a late-September target.
USER: Right. And park the old "memory manager" name for good — it's engram everywhere now.

## Expected

```yaml
existing:  # fixture state the case assumes (seeded by the eval harness)
  - kind: project
    title: "memory manager"  # old working title; attributes carry the real name
    attributes: { name: "engram", status: "idea" }
candidates:
  - kind: project
    attributes:
      name: "engram"
      status: "active"
      target_date: "2026-09-30"
conflicts:
  - conflict_class: duplicate
    detail: "matches existing project memory (formerly 'memory manager') — expect merge/supersede proposal, not a second project"
expected_proposal:
  contains_attribute_update: { status: "active" }
  contains_alias_or_rename: "engram"
must_not_extract:
  - "Congrats"
```
