# ADR-0016: A query engine, not a search feature

- **Status**: accepted (2026-07-12)
- **Deciders**: project owner, architecture session
- **Context**: M2 (roadmap)

## Context

M2 was originally scoped as "FTS5 search". But search is just one *query*. The product
will inevitably need `kind:project status:active tag:opensource confidence>0.8`,
`linked:person/jude`, `updated:last30days`, `has:evidence`, `visibility:private` — and
later semantic (`sqlite-vec`) and graph-traversal operators. If each of those grows its
own flag on `list` or its own endpoint, the read surface fragments and every consumer
(CLI, REST, MCP, dashboard) reinvents filtering.

## Decision

Build **one query language** with **one parser** in the application layer
(`engram_core.application.queries.query_language`), producing a typed, frozen
`MemoryQuerySpec`. Executors are adapters behind the `QueryEngine` port; the SQLite
executor translates the spec into SQL over the projection tables, and **FTS5 full-text
match is just the free-text operator** inside that language.

Grammar (whitespace-separated terms; quoted phrases allowed):

| Term | Meaning |
| --- | --- |
| bare word / `"quoted phrase"` | FTS5 match against title/content/tags |
| `kind:<kind>` | one of the twelve kinds |
| `tag:<tag>` | repeatable, AND semantics |
| `slug:<slug>` | exact slug |
| `visibility:<shared\|private\|restricted>` | spine field |
| `is:archived` / `is:pinned` / `is:stale` | flags (default excludes archived) |
| `confidence>0.8` (also `>=`, `<`, `<=`) | on **effective** (decayed) confidence |
| `updated:last30days` / `updated:today` / `updated:2026-07-01` | recency (also `created:`) |
| `has:evidence` / `has:links` | spine presence |
| `linked:<slug\|uuid>` | graph adjacency, either direction |
| any other `key:value` | kind-attribute equality via `json_extract(attributes, '$.key')` |

The attribute fallthrough is what makes the twelve kind schemas queryable without
twelve query surfaces: `status:active` works because `project` and `goal` declare
`status` in their schemas — no new operator needed per kind.

## Consequences

- CLI `engram search`, REST `/api/v1/search` (M7), and MCP `engram_search` (M6) all
  accept the *same string* and share the parser — one language to document, one to test.
- New capabilities are new operators, not new endpoints: `semantic:` (M5) and graph
  traversal join the language, ranked alongside FTS.
- **Derived-value filters run in the executor, after SQL.** Effective confidence and
  staleness are computed, never stored (ADR-0009), so `confidence>0.8` and `is:stale`
  filter fetched candidates in Python. At personal-memory scale this is exact and cheap;
  if it ever isn't, the scoring *projection* (recomputable columns) is the sanctioned
  fix — not storing scores in `memories`.
- Cursor pagination over ranked (bm25-ordered) results uses an opaque offset cursor;
  id-ordered cursors remain for unranked listings.
- Negation (`-tag:x`) and OR-groups are deliberately absent until a concrete need
  appears (architecture freeze discipline).

## Alternatives considered

1. **Plain FTS search endpoint + filter params** — rejected: every consumer grows its
   own filter vocabulary; FTS becomes privileged instead of being one operator.
2. **SQL passthrough** — rejected: couples every consumer to the projection schema,
   which is disposable by contract.
3. **A full boolean grammar now** — rejected: speculative; the flat AND-of-terms form
   covers every query we can currently name.
