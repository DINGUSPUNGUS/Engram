"""Stage 4: LLMCandidateGenerator — typed candidates, schema-valid or discarded.

The stage rule (docs/intelligence.md §1): an invalid candidate never leaves the
generator. Every candidate is validated against the KindRegistry, must cite at
least one verbatim evidence quote from stage 2, and may link only through the
closed relation vocabulary — violations are dropped and noted, never repaired
silently.
"""

from collections.abc import Sequence
from uuid import UUID

from engram_core.domain.errors import ValidationError
from engram_core.domain.kinds import KindRegistry
from engram_core.domain.values import LinkRelation, MemoryId, MemoryKind
from engram_intelligence.pipeline.extraction import parse_json_items
from engram_intelligence.pipeline.trace import PipelineTrace
from engram_intelligence.pipeline.types import (
    CandidateLink,
    Chunk,
    EntityMention,
    ExtractedEvidence,
    MemoryCandidate,
)
from engram_intelligence.prompts.registry import PromptRegistry
from engram_intelligence.provider import LLMProvider, LLMRequest

_PROMPT_NAME = "candidate-generation"
_STAGE = "candidate_generation"
_CANDIDATE_PREFIX = "candidate:"


class LLMCandidateGenerator:
    """Runs the candidate-generation prompt over the whole evidence set."""

    def __init__(
        self,
        provider: LLMProvider,
        prompts: PromptRegistry,
        kinds: KindRegistry,
        trace: PipelineTrace,
    ) -> None:
        self._provider = provider
        self._prompts = prompts
        self._kinds = kinds
        self._trace = trace

    def generate(
        self,
        chunks: Sequence[Chunk],
        evidence: Sequence[ExtractedEvidence],
        mentions: Sequence[EntityMention],
    ) -> Sequence[MemoryCandidate]:
        if not evidence:
            return ()
        template = self._prompts.get(_PROMPT_NAME)
        rendered = template.body.replace("{entities}", self._entities_block(mentions)).replace(
            "{evidence}", self._evidence_block(evidence)
        )
        request = LLMRequest(
            prompt_name=template.name,
            prompt_version=template.version,
            rendered_prompt=rendered,
            json_output=True,
            max_output_tokens=4096,
        )
        response = self._provider.complete(request)
        try:
            items = parse_json_items(response.text)
        except ValueError as exc:
            self._trace.note(_STAGE, f"unparseable response ({exc}); no candidates")
            return ()

        candidates: list[MemoryCandidate] = []
        for position, item in enumerate(items):
            candidate = self._validate(position, item, evidence, mentions, len(items))
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    # -- validation (the stage's law) --------------------------------------------

    def _validate(
        self,
        position: int,
        item: dict[str, object],
        evidence: Sequence[ExtractedEvidence],
        mentions: Sequence[EntityMention],
        total: int,
    ) -> MemoryCandidate | None:
        try:
            kind = MemoryKind(str(item.get("kind", "")).lower())
        except ValueError:
            self._trace.note(_STAGE, f"candidate {position}: unknown kind {item.get('kind')!r}")
            return None
        if kind is MemoryKind.RELATIONSHIP:
            self._trace.note(_STAGE, f"candidate {position}: relationship kind is not generated")
            return None
        title = str(item.get("title") or "").strip()
        if not title:
            self._trace.note(_STAGE, f"candidate {position}: empty title")
            return None
        raw_attributes = item.get("attributes")
        attributes = dict(raw_attributes) if isinstance(raw_attributes, dict) else {}
        try:
            version = self._kinds.current_version(kind)
            self._kinds.parse(kind, dict(attributes), schema_version=version)
        except ValidationError as exc:
            self._trace.note(
                _STAGE, f"candidate {position} ({title!r}): invalid attributes — {exc}"
            )
            return None

        cited = self._match_evidence(item, evidence)
        if not cited:
            self._trace.note(
                _STAGE, f"candidate {position} ({title!r}): no verbatim evidence cited"
            )
            return None

        links = self._parse_links(position, item, mentions, total)
        return MemoryCandidate(
            kind=kind,
            title=title,
            content=str(item.get("content") or ""),
            attributes=attributes,
            evidence=cited,
            mentions=tuple(m for m in mentions if m.resolved_id is not None),
            links=links,
        )

    def _match_evidence(
        self, item: dict[str, object], evidence: Sequence[ExtractedEvidence]
    ) -> tuple[ExtractedEvidence, ...]:
        """Match cited quotes to stage-2 evidence. Wrapper quote marks the model
        adds around its citation are stripped before lookup — lossless, because
        what attaches is always the stage-2 verbatim ``ExtractedEvidence``,
        never the model's citation string."""
        raw = item.get("evidence_quotes")
        quotes = [str(q).strip() for q in raw] if isinstance(raw, list) else []
        by_quote = {entry.quote: entry for entry in evidence}
        wrappers = "'\"‘’“”"  # noqa: RUF001 — the smart quotes ARE the target
        matched: list[ExtractedEvidence] = []
        for quote in quotes:
            entry = by_quote.get(quote) or by_quote.get(quote.strip(wrappers))
            if entry is not None and entry not in matched:
                matched.append(entry)
        return tuple(matched)

    def _parse_links(
        self,
        position: int,
        item: dict[str, object],
        mentions: Sequence[EntityMention],
        total: int,
    ) -> tuple[CandidateLink, ...]:
        raw = item.get("links")
        if not isinstance(raw, list):
            return ()
        resolved_ids = {str(m.resolved_id) for m in mentions if m.resolved_id is not None}
        links: list[CandidateLink] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            try:
                relation = LinkRelation(str(entry.get("relation", "")).lower())
            except ValueError:
                self._trace.note(
                    _STAGE, f"candidate {position}: unknown relation {entry.get('relation')!r}"
                )
                continue
            target = str(entry.get("target") or "")
            if target.startswith(_CANDIDATE_PREFIX):
                try:
                    index = int(target.removeprefix(_CANDIDATE_PREFIX))
                except ValueError:
                    index = -1
                if not 0 <= index < total or index == position:
                    self._trace.note(_STAGE, f"candidate {position}: bad link target {target!r}")
                    continue
                links.append(CandidateLink(relation=relation, target_candidate_index=index))
            elif target in resolved_ids:
                links.append(
                    CandidateLink(relation=relation, target_memory_id=MemoryId(UUID(target)))
                )
            else:
                self._trace.note(
                    _STAGE,
                    f"candidate {position}: link target {target!r} is neither a candidate"
                    " nor a resolved entity",
                )
        return tuple(links)

    # -- prompt blocks ------------------------------------------------------------

    @staticmethod
    def _entities_block(mentions: Sequence[EntityMention]) -> str:
        lines = [
            f'- {mention.resolved_id} ({mention.kind_guess}): "{mention.surface_text}"'
            for mention in mentions
            if mention.resolved_id is not None
        ]
        return "\n".join(lines) if lines else "(none)"

    @staticmethod
    def _evidence_block(evidence: Sequence[ExtractedEvidence]) -> str:
        return "\n".join(f'- "{entry.quote}" (chunk {entry.chunk_index})' for entry in evidence)
