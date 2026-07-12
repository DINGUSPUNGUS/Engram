# Synthetic Corpus — Scenario Taxonomy

The generator (contract in `engram_intelligence/evals.py`, implementation roadmap
phase 8) produces seeded fake conversations per scenario, **with ground truth attached
at generation time** — scoring is exact, never judged. Generated files are reproducible
from (generator version, seed) and are not committed wholesale; a manifest of hashes is.

| Scenario family | Generates | Stresses | Exact ground truth |
| --- | --- | --- | --- |
| `conflicting-preferences` | Preference stated, later reversed; same vs. different context | ConflictDetector, coexist-vs-supersede rules | Which pairs conflict, which coexist |
| `duplicate-contacts` | Same person introduced twice (nickname, typo, new channel) | EntityResolver alias matching, merge proposals | The duplicate pairs |
| `renamed-business` | Org mentioned, later rebranded | Alias sets, `supersedes` edges | Old→new identity map |
| `job-change` | Person's employer changes over sessions | `works_at` lifecycle, contradiction handling | Edge timeline |
| `contradictory-facts` | Fact stated, later corrected | Confidence math, contradiction queue | Final truth per fact |
| `long-running-project` | One project across dozens of sessions | Cross-session entity resolution, `about` linking | Session→project map |
| `noise` | Small talk, jokes, hypotheticals, task-only context | Extraction precision — what NOT to remember | Empty expected set |
| `adversarial` | Prompt-injection payloads inside conversation content | Pipeline treats content as data (docs/security.md) | Zero instruction-following, flagged evidence |
| `mixed-density` | Realistic blends: 90% noise, 10% durable | End-to-end precision/recall balance | Full expected proposal |

Growth rule: every real-world failure mode observed after launch gets (a) a golden case
reproducing it and (b) a scenario family here so it is tested at scale, before the fix
merges.
