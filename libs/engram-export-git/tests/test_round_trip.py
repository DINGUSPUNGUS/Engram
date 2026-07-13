"""THE M3 invariant: export → delete database → restore → replay ⇒ equivalent state.

Identity, relationships, evidence, confidence inputs, and the events themselves must
all survive. "Equivalent" is checked three ways: the raw event log (ids, payloads,
provenance, order), the projected read models, and a re-export's merkle root.
"""

from pathlib import Path

import pytest
from export_harness import Space, build_space, seed_rich_space

from engram_core.application.dto import MemoryReadModel
from engram_events import EventEnvelope, serialize_payload_json


def _event_view(envelope: EventEnvelope) -> tuple[object, ...]:
    """Everything that must survive, per event. global_seq is the store's own
    counter — equality of the ordered sequence covers it."""
    return (
        str(envelope.event_id),
        str(envelope.stream_id),
        envelope.stream_seq,
        envelope.event_type,
        envelope.schema_version,
        serialize_payload_json(envelope.payload),
        envelope.occurred_at,
        envelope.provenance,
    )


def _memory_view(model: MemoryReadModel) -> tuple[object, ...]:
    return (
        str(model.id),
        model.kind,
        model.slug,
        model.title,
        model.content,
        tuple(sorted(model.attributes.items())),
        model.tags,
        tuple(sorted((link.relation, str(link.target_id)) for link in model.links)),
        tuple(
            (item.evidence_type, item.value, item.note, item.added_at, item.actor)
            for item in model.evidence
        ),
        model.confidence,  # the stored input — decay is derived at read time
        model.lifetime_policy,
        model.visibility,
        model.archived,
        model.created_by,
        model.created_at,
        model.updated_at,
        model.version,
    )


def _all_memories(space: Space) -> list[tuple[object, ...]]:
    return [
        _memory_view(model)
        for model in space.query.list_memories(include_archived=True, limit=200).items
    ]


@pytest.mark.integration
def test_full_round_trip_is_lossless(space: Space, tmp_path: Path) -> None:
    seed_rich_space(space)
    repo = tmp_path / "repo"
    original_report = space.exporter.export(repo)
    original_events = [_event_view(e) for e in space.store.read_all()]
    original_memories = _all_memories(space)
    assert original_events and len(original_memories) == 5

    # "Delete the database": a brand-new empty space stands in for the old one.
    reborn = build_space(tmp_path / "reborn.db")
    report = reborn.importer.restore(repo)
    assert report.events == len(original_events)
    replayed = reborn.rebuild()
    assert replayed == len(original_events)

    # 1. The event log survives verbatim (identity, payloads, provenance, order).
    assert [_event_view(e) for e in reborn.store.read_all()] == original_events
    # 2. The projected state is equivalent (relationships, evidence, confidence
    #    inputs, spine metadata, timestamps, versions).
    assert _all_memories(reborn) == original_memories
    # 3. And the reborn space exports byte-equivalent content.
    re_report = reborn.exporter.export(tmp_path / "re-export")
    assert re_report.manifest.merkle_root == original_report.manifest.merkle_root


@pytest.mark.integration
def test_restore_from_bare_events_file(space: Space, tmp_path: Path) -> None:
    seed_rich_space(space)
    repo = tmp_path / "repo"
    space.exporter.export(repo, export_format="ndjson")
    reborn = build_space(tmp_path / "reborn.db")
    report = reborn.importer.restore(repo / "timeline" / "events.ndjson")
    assert report.events == len(space.store.read_all())
    reborn.rebuild()
    assert _all_memories(reborn) == _all_memories(space)
