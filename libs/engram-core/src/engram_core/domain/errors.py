"""The single error hierarchy for all of engram.

Adapters translate library exceptions (SQLAlchemy, GitPython, …) into these before
they cross a port. Interface layers map them outward exactly once: the API to RFC 9457
problem+json responses, the CLI to exit codes. Nothing catches-and-continues in the
domain or application layer.
"""


class EngramError(Exception):
    """Base class for every error engram raises on purpose."""


class ValidationError(EngramError):
    """Input violates a domain invariant (bad slug, empty title, unknown type…)."""


class NotFoundError(EngramError):
    """The addressed aggregate or resource does not exist (or is deleted)."""


class ConflictError(EngramError):
    """The operation contradicts current state (duplicate slug, merged proposal…)."""


class StaleVersionError(ConflictError):
    """Optimistic concurrency failure: the caller acted on an outdated version.

    Maps to HTTP 409. Clients should re-read and retry.
    """


class StorageError(EngramError):
    """An adapter failed in a way the caller cannot fix (I/O, corruption, locks)."""
