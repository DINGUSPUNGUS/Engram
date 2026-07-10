# ADR-0007: REST, CLI, and MCP are thin shells over the same application services

- **Status**: Accepted
- **Date**: 2026-07-10

## Context

engram ships three-plus interfaces (REST API, CLI, MCP server, someday a VSCode
extension). The classic failure mode is each interface accreting its own slightly
different logic until "create a memory" means three different things.

## Decision

All business behavior lives in the application services of engram-core
(`MemoryCommandService`, `ProposalCommandService`, query services). An interface layer
may only:

1. parse/validate transport input into DTOs,
2. call exactly one service method,
3. map the result/error to its medium (JSON, exit code, MCP content).

"Logic in a router/command/tool-handler is a bug" is a stated review rule in
CONTRIBUTING.md. The MCP app stays deliberately empty until the services it would wrap
exist (roadmap phase 7) — building it earlier would force it to invent logic.

## Consequences

- Behavior is defined once; interfaces cannot drift apart. ✔
- New surfaces (VSCode extension, webhooks) are cheap: one more thin shell. ✔
- Occasionally an interface wants a convenience the service doesn't offer; the fix is a
  service method (or a query), never inline logic — slightly slower in the moment,
  structurally faster forever.
