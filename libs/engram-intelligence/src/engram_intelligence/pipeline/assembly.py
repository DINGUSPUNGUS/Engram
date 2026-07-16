"""Stage 7: DraftProposalAssembler — everything becomes ONE reviewable proposal.

The assembler is the pipeline's only exit, and it speaks the proposal system's
language: draft *intents* (ADR-0018), never events. The M4 reconciliation rule is
honored here for extraction too — a candidate that duplicates an existing memory
becomes an attribute-update + evidence intents against that memory, never a second
``create_memory``; a contradicting candidate is created alongside an explicit
``contradict_memory`` intent and a ``supersedes`` edge, so review sees the clash
stated, not resolved (memory-model.md §8).
"""

from collections.abc import Sequence
from uuid import UUID

from engram_core.application.commands import drafts as d
from engram_core.application.dto import MemoryReadModel
from engram_core.domain.kinds import KindRegistry
from engram_core.domain.ports import MemoryQuery
from engram_core.domain.values import LinkRelation, derive_slug, new_memory_id
from engram_intelligence.pipeline.trace import PipelineTrace
from engram_intelligence.pipeline.types import (
    ConflictClass,
    ConflictReport,
    MemoryCandidate,
    ProposalDraft,
    ScoredCandidate,
    Transcript,
)

_STAGE = "proposal_assembly"


class DraftProposalAssembler:
    """Scored candidates + conflicts -> one ProposalDraft of intents."""

    def __init__(self, query: MemoryQuery, kinds: KindRegistry, trace: PipelineTrace) -> None:
        self._query = query
        self._kinds = kinds
        self._trace = trace

    def assemble(
        self,
        transcript: Transcript,
        scored: Sequence[ScoredCandidate],
        conflicts: Sequence[ConflictReport],
    ) -> ProposalDraft:
        duplicates = self._first_by_index(conflicts, ConflictClass.DUPLICATE)
        contradictions = self._by_index(conflicts, ConflictClass.CONTRADICTION)

        # Every candidate resolves to a target id up front so links can re-point
        # at reconciled existing memories instead of dropped creates.
        targets: dict[int, UUID] = {}
        for index in range(len(scored)):
            duplicate = duplicates.get(index)
            targets[index] = (
                UUID(str(duplicate.existing_id)) if duplicate is not None else new_memory_id()
            )

        intents: list[d.DraftIntent] = []
        lines: list[str] = []
        for index, entry in enumerate(scored):
            candidate = entry.candidate
            if index in duplicates:
                existing = self._query.get(duplicates[index].existing_id)
                intents.extend(self._reconcile(candidate, existing))
                lines.append(
                    f"- reconcile #{index} {candidate.kind.value} {candidate.title!r}"
                    f" into existing {existing.id} (importance {entry.importance:.2f};"
                    f" {entry.rationale})"
                )
            else:
                intents.extend(self._create(candidate, targets[index]))
                lines.append(
                    f"- create #{index} {candidate.kind.value} {candidate.title!r}"
                    f" as {targets[index]} (importance {entry.importance:.2f}; {entry.rationale})"
                )
            for report in contradictions.get(index, ()):
                existing = self._query.get(report.existing_id)
                if targets[index] == UUID(str(existing.id)):
                    continue  # reconciled into the very memory it would contradict
                intents.append(
                    d.ContradictMemoryDraft(
                        memory_id=UUID(str(existing.id)),
                        base_version=existing.version,
                        contradicting_id=targets[index],
                        note=report.detail,
                    )
                )
                intents.append(
                    d.LinkDraft(
                        source_id=targets[index],
                        target_id=UUID(str(existing.id)),
                        relation=LinkRelation.SUPERSEDES.value,
                        base_version=None,
                    )
                )
                lines.append(f"  contradicts {existing.id}: {report.detail}")
            intents.extend(self._links(candidate, index, targets, in_duplicate=index in duplicates))

        session = transcript.source.session_id
        source_line = (
            f"Extracted from a conversation ({transcript.source.actor}"
            + (f", session {session}" if session else "")
            + ")."
        )
        description = "\n".join([source_line, "", *lines])
        return ProposalDraft(
            title=f"Ingest: {len(scored)} candidate(s), {len(conflicts)} conflict(s)",
            description=description,
            proposed_events=tuple(d.to_dict(intent) for intent in intents),
        )

    # -- intent builders ------------------------------------------------------------

    def _create(self, candidate: MemoryCandidate, memory_id: UUID) -> list[d.DraftIntent]:
        confidence = candidate.confidence_prior if candidate.confidence_prior is not None else 0.6
        intents: list[d.DraftIntent] = [
            d.CreateMemoryDraft(
                memory_id=memory_id,
                kind=candidate.kind.value,
                slug=str(derive_slug(candidate.title, memory_id.hex)),
                title=candidate.title,
                content=candidate.content,
                attributes=dict(candidate.attributes),
                attributes_schema_version=self._kinds.current_version(candidate.kind),
                tags=(),
                confidence=confidence,
                lifetime_policy="standard",
                lifetime_until=None,
                visibility="shared",
                base_version=0,
            )
        ]
        intents.extend(
            d.AddEvidenceDraft(
                memory_id=memory_id,
                base_version=None,
                evidence_type=entry.evidence_type.value,
                value=entry.quote,
                note=entry.rationale,
            )
            for entry in candidate.evidence
        )
        return intents

    def _reconcile(
        self, candidate: MemoryCandidate, existing: MemoryReadModel
    ) -> list[d.DraftIntent]:
        """The M4 rule applied to extraction: never a duplicate create."""
        changes = {
            key: value
            for key, value in candidate.attributes.items()
            if value is not None
            and key in existing.attributes
            and existing.attributes.get(key) != value
        }
        intents: list[d.DraftIntent] = []
        if changes:
            intents.append(
                d.UpdateAttributesDraft(
                    memory_id=UUID(str(existing.id)),
                    base_version=existing.version,
                    changes=changes,
                )
            )
        existing_quotes = {entry.value for entry in existing.evidence}
        intents.extend(
            d.AddEvidenceDraft(
                memory_id=UUID(str(existing.id)),
                base_version=existing.version if not intents else None,
                evidence_type=entry.evidence_type.value,
                value=entry.quote,
                note=entry.rationale,
            )
            for entry in candidate.evidence
            if entry.quote not in existing_quotes
        )
        if not intents:
            self._trace.note(
                _STAGE,
                f"candidate {candidate.title!r} adds nothing to existing {existing.id};"
                " no intents proposed",
            )
        return intents

    def _links(
        self,
        candidate: MemoryCandidate,
        index: int,
        targets: dict[int, UUID],
        *,
        in_duplicate: bool,
    ) -> list[d.DraftIntent]:
        intents: list[d.DraftIntent] = []
        for link in candidate.links:
            if link.target_candidate_index is not None:
                target = targets.get(link.target_candidate_index)
            else:
                target = UUID(str(link.target_memory_id))
            if target is None or target == targets[index]:
                self._trace.note(_STAGE, f"candidate {index}: dropped unresolvable/self link")
                continue
            intents.append(
                d.LinkDraft(
                    source_id=targets[index],
                    target_id=target,
                    relation=link.relation.value,
                    base_version=None,
                )
            )
        return intents

    # -- conflict indexing ------------------------------------------------------------

    @staticmethod
    def _first_by_index(
        conflicts: Sequence[ConflictReport], conflict_class: ConflictClass
    ) -> dict[int, ConflictReport]:
        result: dict[int, ConflictReport] = {}
        for report in conflicts:
            if report.conflict_class is conflict_class and report.candidate_index not in result:
                result[report.candidate_index] = report
        return result

    @staticmethod
    def _by_index(
        conflicts: Sequence[ConflictReport], conflict_class: ConflictClass
    ) -> dict[int, tuple[ConflictReport, ...]]:
        result: dict[int, list[ConflictReport]] = {}
        for report in conflicts:
            if report.conflict_class is conflict_class:
                result.setdefault(report.candidate_index, []).append(report)
        return {index: tuple(reports) for index, reports in result.items()}
