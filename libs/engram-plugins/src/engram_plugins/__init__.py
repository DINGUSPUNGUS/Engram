"""engram plugin architecture (ADR-0024): capability-gated gateway + registry.

Plugins are untrusted input, never a trusted authority. This package's whole
job is to make that structurally true: a plugin receives a ``PluginGateway``
that can read (capability-gated) and open exactly one kind of proposal — it
can never append a memory event, approve, or merge anything, and replay never
executes plugin code.
"""

__version__ = "0.1.0"
