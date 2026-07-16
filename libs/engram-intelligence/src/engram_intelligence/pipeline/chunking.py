"""Stage 1: TurnChunker — deterministic, no model involved.

Whole turns are grouped greedily under a character budget; a turn is never split
(a quote extracted later must be verbatim-findable inside exactly one chunk).
"""

from collections.abc import Sequence

from engram_intelligence.pipeline.types import Chunk, Transcript, Turn

_DEFAULT_BUDGET_CHARS = 1600


def render_turn(turn: Turn) -> str:
    """The canonical one-turn rendering used by chunks, prompts, and parsers."""
    return f"{turn.role.value.upper()}: {turn.content}"


class TurnChunker:
    """Greedy turn grouping under a character budget."""

    def __init__(self, budget_chars: int = _DEFAULT_BUDGET_CHARS) -> None:
        self._budget = budget_chars

    def chunk(self, transcript: Transcript) -> Sequence[Chunk]:
        chunks: list[Chunk] = []
        lines: list[str] = []
        start = 0
        size = 0
        for index, turn in enumerate(transcript.turns):
            rendered = render_turn(turn)
            if lines and size + len(rendered) > self._budget:
                chunks.append(self._make(len(chunks), lines, start, index - 1))
                lines, start, size = [], index, 0
            lines.append(rendered)
            size += len(rendered) + 1
        if lines:
            chunks.append(self._make(len(chunks), lines, start, len(transcript.turns) - 1))
        return chunks

    @staticmethod
    def _make(index: int, lines: list[str], turn_start: int, turn_end: int) -> Chunk:
        return Chunk(index=index, text="\n".join(lines), turn_start=turn_start, turn_end=turn_end)
