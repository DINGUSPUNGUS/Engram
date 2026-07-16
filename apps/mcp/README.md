# @engram/mcp

MCP server for engram — **a stub awaiting its transport**. The behavior it will
expose already exists: the assistant gateway (`libs/engram-assistants`, ADR-0020,
[docs/integrations.md](../../docs/integrations.md)).

## Why it's still empty

The MCP server is a thin stdio shell over the `AssistantGateway` (ADR-0007): the
five canonical tools (`engram_search/recall/remember/proposal_status/timeline`),
capability negotiation, the recall boundary, and structural consent (no review
verbs — nothing an assistant submits becomes memory until the user merges the
proposal) are all defined once in the gateway and fully tested there. This app
adds only the MCP protocol framing.

Note the M4/M5 correction to the original plan: `engram_remember` never calls
`create_memory` — it runs the intelligence pipeline and opens ONE Proposal; and
`engram_forget` is deferred until an archive draft intent exists (an ADR-worthy
proposal-workflow addition, not to be smuggled in through a tool).
