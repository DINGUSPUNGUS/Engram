## What & why

<!-- One paragraph. Link the issue. -->

## Checklist

- [ ] CI green (lint, layering contract, typecheck, tests, contract drift)
- [ ] Tests cover the behavior change (given-events / when-command / then-events for
      event-sourced code)
- [ ] No logic in interface layers (routers/CLI/MCP handlers only parse → delegate → map)
- [ ] Event payload shapes unchanged, or `schema_version` bumped with an upcaster
- [ ] ADR added/updated if this changes an architectural decision
- [ ] Docs updated in the same PR (`docs/`, `.env.example`, README as applicable)
