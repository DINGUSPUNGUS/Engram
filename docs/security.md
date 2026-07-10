# Security

## Threat model (local-first)

engram runs on the user's machine and stores the user's accumulated memory — potentially
years of personal and professional context. The data is the crown jewel; the network
surface is deliberately tiny.

| Surface | Risk | Stance |
| --- | --- | --- |
| API port | Anything reaching it can read/write all memories | Binds `127.0.0.1` by default. Do not expose beyond loopback before the auth milestone. Changing the bind host is an explicit, documented opt-in. |
| Memory content → LLMs | **Prompt injection**: a memory can contain instructions ("ignore previous instructions and…") that an assistant may obey when the memory is recalled | Recalled content is *data, not instructions*. The MCP server will wrap recalled memories in clearly delimited, role-separated context. This is documented and mitigated, not solved — no one has solved it. |
| LLM → memory | A malicious or confused assistant writing garbage or exfil-bait into shared memory | Provenance on every event (who wrote what); PR-style proposals put a human between extraction and persistence; undo/timeline make damage visible and reversible. |
| Export repo | Contains everything; a public remote = total disclosure | Treated like a password-manager vault in all docs. Roadmap: a pre-commit secret scanner hook in the export repo and a "remote is private?" check in `engram init`. |
| Slug → filesystem | Path traversal via crafted slugs | Slug alphabet is `[a-z0-9-]` (validated at construction) and the exporter additionally resolves-and-verifies containment (`layout.resolve_inside`). Tested. |
| Event payloads in logs | Memory content leaking into log shippers | Logging policy: envelope metadata only, never payload bodies (operations.md). |
| Supply chain | Malicious dependency update | Lockfiles committed (pnpm-lock.yaml, uv.lock), dependabot PRs, CI runs everything before merge. |

## Authentication: deliberately absent, deliberately seamed

There is no auth (per the project's current scope). The seam is reserved so adding it is
not a refactor: every router already depends on `get_principal()` 
(`engram_api/dependencies.py`), which today derives a `Provenance` from the
`X-Engram-Actor` header. The auth milestone swaps that dependency's implementation
(token → principal) and touches nothing else. Until then: loopback only.

## Reporting

See [SECURITY.md](../SECURITY.md) at the repo root for the disclosure process.
