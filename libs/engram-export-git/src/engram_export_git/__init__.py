"""engram-export-git: the user-owned representation (ADR-0001).

Projects the event log into a git repository the user fully controls:
markdown files (human-readable state) plus NDJSON event exports
(machine-replayable history). Also hosts the inbound reconciler that turns
direct file edits back into events. Everything here is a *projection* —
the SQLite event log remains the system of record.
"""
