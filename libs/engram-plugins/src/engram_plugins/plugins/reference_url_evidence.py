"""Reference plugin (ADR-0024 "Reference plugin"): finds URLs mentioned in a
memory's own content that are not yet backed by evidence, and proposes citing
them.

Deliberately small and deliberately deterministic — no LLM, no network call,
no clock read. The whole flow, end to end:

    declared capabilities (query, evidence_read, proposal_submit)
        → PluginGateway.query()          (existing QueryEngine port, ADR-0016)
        → PluginGateway.evidence_for()   (existing evidence read model)
        → candidate knowledge            (URLs in content, not yet cited)
        → PluginGateway.submit_proposal()  (existing ProposalCommandService door)
        → human review → merge           (unchanged CLI/API/dashboard surfaces)
        → provenance                     (engram_plugins.provenance)
        → replay                         (never touches this module)

Nothing here imports the event store, a repository, or any storage adapter —
only the capability-gated gateway it is handed.
"""

import re
from dataclasses import dataclass
from uuid import UUID

from engram_core.application.commands.drafts import AddEvidenceDraft, DraftIntent
from engram_core.domain.values import MemoryId
from engram_plugins.contract import Capability, PluginContext, PluginDescriptor, PluginRunResult
from engram_plugins.gateway import PluginGateway

PLUGIN_ID = "dev.engram.reference-url-evidence"

_URL_PATTERN = re.compile(r"https?://[^\s)>\]]+")
_TRAILING_PUNCTUATION = ".,;:!?)>]}\"'"
_EVIDENCE_TYPE = "uri"
_DEFAULT_QUERY = "http"  # a term any URL-bearing memory's content will match


def _extract_urls(content: str) -> tuple[str, ...]:
    """Bare URLs in prose text, trailing sentence punctuation stripped
    (``"see https://x.example, thanks"`` must not cite ``"https://x.example,"``).
    De-duplicated, order-stable."""
    seen: dict[str, None] = {}
    for match in _URL_PATTERN.findall(content):
        url = match.rstrip(_TRAILING_PUNCTUATION)
        if url:
            seen[url] = None
    return tuple(seen)


@dataclass(frozen=True, slots=True)
class ReferenceUrlEvidencePlugin:
    """One plugin object per registration; stateless across runs."""

    version: str = "1.0.0"

    @property
    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id=PLUGIN_ID,
            name="Reference URL Evidence Suggester",
            version=self.version,
            api_version=1,
            capabilities=frozenset(
                {Capability.QUERY, Capability.EVIDENCE_READ, Capability.PROPOSAL_SUBMIT}
            ),
            description=(
                "Finds bare URLs in a memory's own content that are not yet cited as"
                " evidence, and proposes adding them. Deterministic, rule-based — no AI."
            ),
        )

    def run(self, context: PluginContext, gateway: PluginGateway) -> PluginRunResult:
        query_text = str(context.config.get("query", _DEFAULT_QUERY))
        candidates = gateway.query(query_text, descriptor=self.descriptor, context=context)

        drafts: list[DraftIntent] = []
        touched: list[str] = []
        for memory in candidates:
            urls = _extract_urls(memory.content)
            if not urls:
                continue
            existing = gateway.evidence_for(
                MemoryId(UUID(memory.id)), descriptor=self.descriptor, context=context
            )
            cited = {e.value for e in existing if e.evidence_type == _EVIDENCE_TYPE}
            for url in urls:
                if url in cited:
                    continue
                drafts.append(
                    AddEvidenceDraft(
                        memory_id=UUID(memory.id),
                        # Evidence is additive, never contested (the same
                        # convention the codebase's own v1→v2 draft upcast
                        # uses for add_evidence): unchecked base_version, so
                        # the two MemoryAccessed events this very run causes
                        # via `query`/`evidence_for` can never self-conflict
                        # with the evidence draft they led to.
                        base_version=None,
                        evidence_type=_EVIDENCE_TYPE,
                        value=url,
                        note=f"found in content by {PLUGIN_ID}@{self.version}",
                    )
                )
                touched.append(memory.id)

        if not drafts:
            return PluginRunResult(
                ok=True,
                proposal_id=None,
                candidate_count=0,
                note=f"scanned {len(candidates)} memor{'y' if len(candidates) == 1 else 'ies'};"
                " nothing to propose",
            )

        proposal_id = gateway.submit_proposal(
            title="Untracked URLs found in memory content",
            description=(
                f"{PLUGIN_ID}@{self.version} found {len(drafts)} URL(s) across"
                f" {len(set(touched))} memor{'y' if len(set(touched)) == 1 else 'ies'} that are"
                " mentioned in content but not yet cited as evidence."
            ),
            drafts=drafts,
            descriptor=self.descriptor,
            context=context,
        )
        return PluginRunResult(
            ok=True,
            proposal_id=proposal_id,
            candidate_count=len(drafts),
            note=f"opened proposal {proposal_id} with {len(drafts)} evidence draft(s)",
        )
