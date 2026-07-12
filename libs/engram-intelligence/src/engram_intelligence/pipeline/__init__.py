"""The memory ingestion pipeline: nine stages from conversation to Proposal.

Stage boundaries are frozen dataclasses (``types``), stage contracts are Protocols
(``stages``), orchestration is ``orchestrator``. Design of record:
docs/intelligence.md §1. Terminal output is always a Proposal — never a direct write.
"""
