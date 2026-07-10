# @engram/mcp

MCP server for engram — **deliberately a stub** until roadmap phase 7.

## Why it's empty

The MCP server must be a thin shell over the same application services the REST API and
CLI use (ADR-0007). Building it before those services exist would force it to invent its
own logic, which is exactly the duplication the architecture forbids.

## Planned tool surface

| MCP tool | Application service call |
| --- | --- |
| `engram_search` | `SearchQueryService.search` + `record_access` |
| `engram_recall` | `MemoryQueryService.get_memory` + `record_access` |
| `engram_remember` | `MemoryCommandService.create_memory` (or a Proposal when review is on) |
| `engram_forget` | `MemoryCommandService.archive_memory` |
| `engram_timeline` | `TimelineQueryService.memory_timeline` |

Provenance: every tool call carries the assistant's identity into the event log's
`provenance` field — that is how a shared memory stays auditable across ChatGPT, Claude,
Gemini, Cursor, Copilot, and local models.
