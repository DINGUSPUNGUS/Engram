"""engram-intelligence: how AI enters engram, and the walls that keep it honest.

Design of record: docs/intelligence.md. The prime directive (ADR-0011/0012): **AI
proposes; events decide.** Nothing in this package writes to a memory stream — the
pipeline's single terminal output is a Proposal handed to the ordinary review flow.

engram-core does not import this package, ever (import-linter enforced). Vendor SDKs
may only be imported inside :mod:`engram_intelligence.providers`.
"""

__version__ = "0.1.0"
