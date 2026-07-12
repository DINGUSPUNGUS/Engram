"""engram-observatory: explainability as a subsystem, not an afterthought (ADR-0015).

Not logging — an **audit graph**. Every consequential decision (a memory proposed or
rejected, a confidence assigned, a duplicate detected, an evaluation failed) records a
``DecisionTrace``: which rules fired, which heuristics rejected, which prompt@version
and model produced what, which evidence supported it. "Why did engram do that?" must
always have a reconstructable answer — the product principle is **boringly
trustworthy**: predictable, explainable, reproducible, versioned, reversible.

Reserved in Phase 0.9; implementations land alongside the subsystems they explain.
"""

__version__ = "0.1.0"
