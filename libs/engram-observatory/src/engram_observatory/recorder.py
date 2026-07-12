"""Trace recording contract + the in-memory implementation.

The pipeline, conflict rules, scoring projection, and eval harness all record here.
A SQLite-backed recorder (rebuildable-projection semantics where derivable, durable
where not) lands with the first subsystem that emits traces.
"""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from engram_observatory.trace import DecisionTrace, TraceSubject


class TraceRecorder(Protocol):
    """Append-only sink and query surface for decision traces."""

    def record(self, trace: DecisionTrace) -> None: ...

    def for_subject(self, subject: TraceSubject, subject_id: UUID) -> Sequence[DecisionTrace]:
        """All traces about one subject, oldest first."""
        ...


class InMemoryTraceRecorder:
    """Process-local recorder for tests and ephemeral runs."""

    def __init__(self) -> None:
        self._traces: list[DecisionTrace] = []

    def record(self, trace: DecisionTrace) -> None:
        self._traces.append(trace)

    def for_subject(self, subject: TraceSubject, subject_id: UUID) -> Sequence[DecisionTrace]:
        return [
            trace
            for trace in self._traces
            if trace.subject is subject and trace.subject_id == subject_id
        ]
