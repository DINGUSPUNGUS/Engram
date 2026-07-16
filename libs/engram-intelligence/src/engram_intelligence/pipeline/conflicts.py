"""Stage 5: RuleConflictDetector — deterministic duplicate/contradiction rules.

Attribute-equality checks against current state, exactly the memory-model.md §8
classes. Detection only: resolution belongs to review (the iron rule — the system
never silently picks a winner). No model involved; these rules run in CI always.
"""

from collections.abc import Iterator, Sequence

from engram_core.application.dto import MemoryReadModel
from engram_core.domain.ports import MemoryQuery
from engram_core.domain.values import MemoryKind
from engram_intelligence.pipeline.resolution import entity_names
from engram_intelligence.pipeline.types import (
    ConflictClass,
    ConflictReport,
    MemoryCandidate,
)


def _casefold_set(values: Sequence[str]) -> set[str]:
    return {value.casefold().strip() for value in values if value.strip()}


def _candidate_names(candidate: MemoryCandidate) -> set[str]:
    names = [candidate.title]
    for key in ("full_name", "name"):
        value = candidate.attributes.get(key)
        if isinstance(value, str):
            names.append(value)
    aliases = candidate.attributes.get("aliases")
    if isinstance(aliases, list):
        names.extend(str(alias) for alias in aliases)
    return _casefold_set(names)


class RuleConflictDetector:
    """Compares candidates against the state projection, kind by kind."""

    def __init__(self, query: MemoryQuery) -> None:
        self._query = query

    def detect(self, candidates: Sequence[MemoryCandidate]) -> Sequence[ConflictReport]:
        reports: list[ConflictReport] = []
        for index, candidate in enumerate(candidates):
            reports.extend(self._detect_one(index, candidate))
        return reports

    def _detect_one(self, index: int, candidate: MemoryCandidate) -> Iterator[ConflictReport]:
        for existing in self._existing(candidate.kind):
            report = self._compare(index, candidate, existing)
            if report is not None:
                yield report

    def _compare(
        self, index: int, candidate: MemoryCandidate, existing: MemoryReadModel
    ) -> ConflictReport | None:
        match candidate.kind:
            case (
                MemoryKind.PERSON
                | MemoryKind.ORGANIZATION
                | MemoryKind.LOCATION
                | MemoryKind.ASSET
                | MemoryKind.PROJECT
                | MemoryKind.SKILL
            ):
                overlap = _candidate_names(candidate) & _casefold_set(entity_names(existing))
                if overlap:
                    return self._duplicate(
                        index, existing, f"name/alias overlap: {sorted(overlap)}"
                    )
            case MemoryKind.CONTACT:
                if self._same_attribute(candidate, existing, "channel") and self._same_attribute(
                    candidate, existing, "value"
                ):
                    return self._duplicate(index, existing, "same channel and value")
            case MemoryKind.FACT | MemoryKind.GOAL:
                if self._same_attribute(candidate, existing, "statement"):
                    return self._duplicate(index, existing, "same statement")
            case MemoryKind.PREFERENCE:
                return self._compare_preference(index, candidate, existing)
            case _:
                return None
        return None

    def _compare_preference(
        self, index: int, candidate: MemoryCandidate, existing: MemoryReadModel
    ) -> ConflictReport | None:
        """Preferences with different context coexist; same context conflicts
        (memory-model.md §8) — identical polarity is a duplicate, anything else
        is a contradiction proposing supersession."""
        context = candidate.attributes.get("context")
        existing_context = existing.attributes.get("context")
        if not isinstance(context, str) or not isinstance(existing_context, str):
            return None
        if context.casefold().strip() != existing_context.casefold().strip():
            return None  # coexistence
        polarity = str(candidate.attributes.get("polarity") or "")
        existing_polarity = str(existing.attributes.get("polarity") or "")
        same_title = candidate.title.casefold() == existing.title.casefold()
        if polarity == existing_polarity and same_title:
            return self._duplicate(index, existing, f"same preference in context {context!r}")
        return ConflictReport(
            candidate_index=index,
            conflict_class=ConflictClass.CONTRADICTION,
            existing_id=existing.id,
            detail=(
                f"same context {context!r} as existing preference {existing.title!r}"
                " — newest proposed as superseding (memory-model.md §8)"
            ),
        )

    # -- helpers ------------------------------------------------------------------

    @staticmethod
    def _duplicate(index: int, existing: MemoryReadModel, detail: str) -> ConflictReport:
        return ConflictReport(
            candidate_index=index,
            conflict_class=ConflictClass.DUPLICATE,
            existing_id=existing.id,
            detail=f"matches existing {existing.kind.value} {existing.title!r}: {detail}",
        )

    @staticmethod
    def _same_attribute(candidate: MemoryCandidate, existing: MemoryReadModel, key: str) -> bool:
        mine = candidate.attributes.get(key)
        theirs = existing.attributes.get(key)
        if not isinstance(mine, str) or not isinstance(theirs, str):
            return False
        return mine.casefold().strip() == theirs.casefold().strip()

    def _existing(self, kind: MemoryKind) -> Iterator[MemoryReadModel]:
        cursor: str | None = None
        while True:
            page = self._query.list_memories(kind=kind, cursor=cursor, limit=200)
            yield from page.items
            if page.next_cursor is None:
                return
            cursor = page.next_cursor
