"""Contract tests for the audit-graph types and the in-memory recorder."""

from datetime import UTC, datetime

import pytest
from engram_observatory.recorder import InMemoryTraceRecorder
from engram_observatory.trace import DecisionTrace, StepCategory, TraceStep, TraceSubject

from engram_events import Provenance, new_uuid7


def _trace(subject_id: object) -> DecisionTrace:
    return DecisionTrace(
        trace_id=new_uuid7(),
        subject=TraceSubject.MEMORY,
        subject_id=subject_id,  # type: ignore[arg-type]
        question="why was this memory created?",
        outcome="created via proposal p1",
        steps=(
            TraceStep(
                seq=1,
                category=StepCategory.PROMPT,
                label="extraction",
                prompt_ref="evidence-extraction@1",
                model_id="fake",
            ),
            TraceStep(seq=2, category=StepCategory.RULE, label="kind schema valid"),
            TraceStep(seq=3, category=StepCategory.DECISION, label="proposed"),
        ),
        occurred_at=datetime.now(UTC),
        provenance=Provenance(actor="test"),
    )


@pytest.mark.unit
def test_recorder_filters_by_subject() -> None:
    recorder = InMemoryTraceRecorder()
    memory_a, memory_b = new_uuid7(), new_uuid7()
    recorder.record(_trace(memory_a))
    recorder.record(_trace(memory_b))
    recorder.record(_trace(memory_a))

    traces = recorder.for_subject(TraceSubject.MEMORY, memory_a)
    assert len(traces) == 2
    assert all(trace.subject_id == memory_a for trace in traces)
    assert recorder.for_subject(TraceSubject.PROPOSAL, memory_a) == []


@pytest.mark.unit
def test_steps_carry_prompt_and_model_provenance() -> None:
    trace = _trace(new_uuid7())
    prompt_step = trace.steps[0]
    assert prompt_step.prompt_ref == "evidence-extraction@1"
    assert prompt_step.model_id == "fake"
