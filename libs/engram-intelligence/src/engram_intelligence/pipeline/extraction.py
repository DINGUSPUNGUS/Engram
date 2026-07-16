"""Stage 2: LLMEvidenceExtractor — quotes worth remembering, verbatim or nothing.

Precision over recall: a quote the model paraphrased is rejected (it must appear
character-for-character in its chunk — the quote becomes audit evidence), and a
chunk whose response cannot be parsed contributes nothing rather than corrupting
the run. Every drop is noted in the trace: absence needs explaining too.
"""

import json
from collections.abc import Sequence

from engram_core.domain.values import EvidenceType
from engram_intelligence.pipeline.trace import PipelineTrace
from engram_intelligence.pipeline.types import Chunk, ExtractedEvidence
from engram_intelligence.prompts.registry import PromptRegistry
from engram_intelligence.provider import LLMProvider, LLMRequest

_PROMPT_NAME = "evidence-extraction"
_STAGE = "evidence_extraction"


def parse_json_items(text: str) -> list[dict[str, object]]:
    """Parse a model response expected to be a JSON array of objects.

    Tolerates the common ``format=json`` wrapper (a single-key object holding
    the array) — small local models often emit it despite instructions.

    Raises:
        ValueError: not JSON, or no array of objects present.
    """
    data = json.loads(text)
    if isinstance(data, dict):
        arrays = [value for value in data.values() if isinstance(value, list)]
        if len(arrays) == 1:
            data = arrays[0]
        elif not arrays and all(not isinstance(v, (dict, list)) for v in data.values()):
            data = [data]  # a bare single object
        else:
            raise ValueError("expected a JSON array")
    if not isinstance(data, list):
        raise ValueError("expected a JSON array")
    return [item for item in data if isinstance(item, dict)]


class LLMEvidenceExtractor:
    """Runs the evidence-extraction prompt per chunk and validates the output."""

    def __init__(
        self, provider: LLMProvider, prompts: PromptRegistry, trace: PipelineTrace
    ) -> None:
        self._provider = provider
        self._prompts = prompts
        self._trace = trace

    def extract(self, chunks: Sequence[Chunk]) -> Sequence[ExtractedEvidence]:
        template = self._prompts.get(_PROMPT_NAME)
        evidence: list[ExtractedEvidence] = []
        seen: set[str] = set()
        for chunk in chunks:
            request = LLMRequest(
                prompt_name=template.name,
                prompt_version=template.version,
                rendered_prompt=template.body.replace("{chunk}", chunk.text),
                json_output=True,
            )
            response = self._provider.complete(request)
            try:
                items = parse_json_items(response.text)
            except ValueError as exc:
                self._trace.note(_STAGE, f"chunk {chunk.index}: unparseable response ({exc})")
                continue
            unquoted = 0
            for item in items:
                quote = str(item.get("quote") or "").strip()
                if not quote:
                    unquoted += 1
                    continue
                if quote in seen:
                    continue
                if quote not in chunk.text:
                    self._trace.note(
                        _STAGE, f"chunk {chunk.index}: dropped non-verbatim quote {quote[:60]!r}"
                    )
                    continue
                seen.add(quote)
                evidence.append(
                    ExtractedEvidence(
                        chunk_index=chunk.index,
                        quote=quote,
                        evidence_type=EvidenceType.QUOTE,
                        rationale=str(item["reason"]) if item.get("reason") else None,
                    )
                )
            if unquoted:
                self._trace.note(
                    _STAGE,
                    f"chunk {chunk.index}: {unquoted} item(s) carried no 'quote' field"
                    " — response shape ignored",
                )
        return evidence
