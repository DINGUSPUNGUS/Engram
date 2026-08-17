"""Event store integration: append, typed round-trip, optimistic concurrency."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session

from engram_core.domain.errors import StorageError
from engram_core.domain.events import MemoryCreated, MemoryLifetimeChanged, build_registry
from engram_events import EventEnvelope, OptimisticConcurrencyError, Provenance, new_uuid7
from engram_storage_sqlite.event_store import SqliteEventStore
from engram_storage_sqlite.models import EventRecord


@pytest.fixture
def store(engine: Engine) -> SqliteEventStore:
    return SqliteEventStore(engine, build_registry())


def _envelope(stream_id: UUID, seq: int, payload: object) -> EventEnvelope:
    return EventEnvelope(
        event_id=new_uuid7(),
        stream_id=stream_id,
        stream_seq=seq,
        event_type=type(payload).__name__,
        schema_version=1,
        payload=payload,
        occurred_at=datetime(2026, 7, 12, 9, 30, tzinfo=UTC),
        provenance=Provenance(actor="user", session_id="s1"),
    )


def _created(memory_id: UUID) -> MemoryCreated:
    return MemoryCreated(
        memory_id=memory_id,
        kind="project",
        slug="engram",
        title="engram",
        content="body",
        attributes={"name": "engram", "status": "active"},
        tags=("oss", "infra"),
        confidence=0.9,
        lifetime_policy="until",
        lifetime_until=datetime(2026, 12, 31, tzinfo=UTC),
    )


@pytest.mark.integration
def test_append_assigns_global_order_and_round_trips_types(store: SqliteEventStore) -> None:
    stream = new_uuid7()
    payload = _created(stream)
    appended = store.append(
        [_envelope(stream, 1, payload), _envelope(stream, 2, MemoryLifetimeChanged("standard"))]
    )
    assert [env.global_seq for env in appended] == [1, 2]

    replayed = store.read_stream(stream)
    assert len(replayed) == 2
    restored = replayed[0].payload
    assert restored == payload
    assert isinstance(restored.memory_id, UUID)  # str in SQLite, UUID after decode
    assert isinstance(restored.tags, tuple)
    assert restored.lifetime_until == datetime(2026, 12, 31, tzinfo=UTC)
    assert replayed[0].provenance == Provenance(actor="user", session_id="s1")
    assert replayed[0].occurred_at.tzinfo is not None


@pytest.mark.integration
def test_optimistic_concurrency_conflict(store: SqliteEventStore) -> None:
    stream = new_uuid7()
    store.append([_envelope(stream, 1, _created(stream))])
    with pytest.raises(OptimisticConcurrencyError) as excinfo:
        store.append([_envelope(stream, 1, MemoryLifetimeChanged("standard"))])
    assert excinfo.value.actual_seq == 1


@pytest.mark.integration
def test_read_all_pages_by_global_seq(store: SqliteEventStore) -> None:
    for _ in range(3):
        stream = new_uuid7()
        store.append([_envelope(stream, 1, _created(stream))])
    first_two = store.read_all(limit=2)
    rest = store.read_all(after_global_seq=first_two[-1].global_seq or 0)
    assert len(first_two) == 2
    assert len(rest) == 1
    assert (rest[0].global_seq or 0) > (first_two[-1].global_seq or 0)


@pytest.mark.integration
def test_unknown_event_type_fails_safely_instead_of_raw_crash(
    store: SqliteEventStore, engine: Engine
) -> None:
    """PRE-M10 GATE finding (event sourcing / security P1, confirmed by two
    independent audits): a row naming an event type this build's registry has
    no registration for — a downgraded binary, an uninstalled plugin, a
    corrupted row — used to propagate a raw ``UnknownEventTypeError`` (not an
    ``EngramError``) straight out of ``read_all``/``read_stream``, past every
    ``EngramError`` boundary the CLI/API rely on, contradicting `engram
    rebuild`'s own "(always safe)" messaging. Confirmed via a real
    ``engram rebuild``/``status --verify`` run against a hand-corrupted
    database before this fix landed: a full Python traceback, exit code 1
    (not even the documented 70), no actionable guidance.
    """
    stream = new_uuid7()
    store.append([_envelope(stream, 1, _created(stream))])
    with Session(engine) as session:
        session.add(
            EventRecord(
                event_id=str(new_uuid7()),
                stream_id=str(stream),
                stream_seq=2,
                event_type="MemoryCreatedFutureBogusType",
                schema_version=1,
                payload="{}",
                occurred_at=datetime(2026, 7, 12, 9, 30),
                provenance='{"actor": "user"}',
            )
        )
        session.commit()

    with pytest.raises(StorageError, match="MemoryCreatedFutureBogusType"):
        store.read_all()
    with pytest.raises(StorageError, match="MemoryCreatedFutureBogusType"):
        store.read_stream(stream)


@pytest.mark.integration
def test_future_schema_version_fails_safely_instead_of_silent_misinterpretation(
    store: SqliteEventStore, engine: Engine
) -> None:
    """PRE-M10 follow-up finding: a row whose ``schema_version`` is *newer*
    than this build's registry knows about (written by a newer ``engram``,
    then read by this one, e.g. after a downgrade) used to skip
    ``EventRegistry.upcast()``'s migration loop entirely — the loop only ran
    while ``version < registration.schema_version`` — and return the raw,
    unmigrated payload dict unchanged, silently misinterpreted as the
    current shape instead of refused. Same class of defect as the
    unknown-event-type case above (and the same fix shape: refuse via
    ``UnknownEventTypeError``, translated here into the identical, already
    newer-engram-aware ``StorageError`` message), just triggered by a
    version number instead of a type name.
    """
    stream = new_uuid7()
    store.append([_envelope(stream, 1, _created(stream))])
    with Session(engine) as session:
        session.add(
            EventRecord(
                event_id=str(new_uuid7()),
                stream_id=str(stream),
                stream_seq=2,
                event_type="MemoryLifetimeChanged",
                schema_version=999,  # no build of engram has ever written this
                payload='{"lifetime_policy": "standard"}',
                occurred_at=datetime(2026, 7, 12, 9, 30),
                provenance='{"actor": "user"}',
            )
        )
        session.commit()

    with pytest.raises(StorageError, match="newer engram"):
        store.read_stream(stream)


@pytest.mark.integration
def test_corrupted_payload_json_fails_safely_instead_of_raw_crash(
    store: SqliteEventStore, engine: Engine
) -> None:
    """Same class of defect as the unknown-event-type case above, just via a
    payload column that isn't valid JSON (bit rot, a hand-edited row, a
    truncated write) rather than an unregistered type name."""
    stream = new_uuid7()
    store.append([_envelope(stream, 1, _created(stream))])
    with Session(engine) as session:
        session.add(
            EventRecord(
                event_id=str(new_uuid7()),
                stream_id=str(stream),
                stream_seq=2,
                event_type="MemoryLifetimeChanged",
                schema_version=1,
                payload="{not valid json",
                occurred_at=datetime(2026, 7, 12, 9, 30),
                provenance='{"actor": "user"}',
            )
        )
        session.commit()

    with pytest.raises(StorageError, match="corrupted stored data"):
        store.read_stream(stream)
