"""Stage 3: HeuristicEntityResolver — deterministic alias-set matching.

Existing entity memories (person, organization, location, asset) are matched
against the conversation by name and alias (memory-model.md §9). No model, no
guessing: an exact case-insensitive occurrence resolves; anything less stays
unresolved — a wrongly guessed id corrupts the graph, an unresolved mention
merely creates a reviewable duplicate candidate.
"""

from collections.abc import Iterator, Sequence

from engram_core.application.dto import MemoryReadModel
from engram_core.domain.ports import MemoryQuery
from engram_core.domain.values import MemoryKind
from engram_intelligence.pipeline.types import Chunk, EntityMention, ExtractedEvidence

_ENTITY_KINDS = (
    MemoryKind.PERSON,
    MemoryKind.ORGANIZATION,
    MemoryKind.LOCATION,
    MemoryKind.ASSET,
)
_ALIAS_ATTRIBUTE_KEYS = ("full_name", "name", "aliases", "identifier")


def entity_names(model: MemoryReadModel) -> tuple[str, ...]:
    """Every name this entity answers to: title + name-ish attributes + aliases."""
    names: dict[str, None] = {model.title.strip(): None}
    for key in _ALIAS_ATTRIBUTE_KEYS:
        value = model.attributes.get(key)
        if isinstance(value, str) and value.strip():
            names[value.strip()] = None
        elif isinstance(value, list):
            for alias in value:
                if isinstance(alias, str) and alias.strip():
                    names[alias.strip()] = None
    return tuple(names)


class HeuristicEntityResolver:
    """Resolves mentions against the current state projection."""

    def __init__(self, query: MemoryQuery) -> None:
        self._query = query

    def resolve(
        self, chunks: Sequence[Chunk], evidence: Sequence[ExtractedEvidence]
    ) -> Sequence[EntityMention]:
        corpus = "\n".join(chunk.text for chunk in chunks).casefold()
        mentions: list[EntityMention] = []
        for kind in _ENTITY_KINDS:
            for entity in self._iter_entities(kind):
                for name in entity_names(entity):
                    if len(name) >= 3 and name.casefold() in corpus:
                        mentions.append(
                            EntityMention(
                                surface_text=name,
                                kind_guess=kind,
                                resolved_id=entity.id,
                                resolution_confidence=1.0,
                            )
                        )
                        break  # one mention per entity is enough
        return mentions

    def _iter_entities(self, kind: MemoryKind) -> Iterator[MemoryReadModel]:
        cursor: str | None = None
        while True:
            page = self._query.list_memories(kind=kind, cursor=cursor, limit=200)
            yield from page.items
            if page.next_cursor is None:
                return
            cursor = page.next_cursor
