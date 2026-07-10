"""engram-storage-sqlite: the canonical runtime store (ADR-0001).

Owns the append-only ``events`` table (system of record) and the state projection
tables. Everything here is rebuildable from the event log except the log itself.
Schema changes go through Alembic — never edit tables in place.
"""
