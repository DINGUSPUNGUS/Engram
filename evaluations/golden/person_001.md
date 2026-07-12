---
id: person_001
scenario: duplicate-contacts
stages: [evidence_extraction, entity_resolution, candidate_generation, conflict_detection]
---

## Conversation

USER: Quick intro — my colleague Sarah Chen is joining the kahnya project next week.
Her work email is sarah.chen@acme.io.
ASSISTANT: Great, I'll keep that in mind. Should she get access to the design docs?
USER: Yes. Oh and heads up, people sometimes call her "SC" in standups.
ASSISTANT: Noted — Sarah Chen (SC), joining the kahnya project, sarah.chen@acme.io.

## Expected

```yaml
candidates:
  - kind: person
    attributes:
      full_name: "Sarah Chen"
      aliases: ["SC"]
    links:
      - { relation: involves_inverse_of, note: "kahnya project involves this person" }
  - kind: contact
    attributes: { channel: email, value: "sarah.chen@acme.io", label: "work" }
    links:
      - { relation: owned_by, target: candidate:0 }
evidence_min_count: 2
conflicts: []
must_not_extract:
  - "Should she get access"   # assistant question, not durable knowledge
```
