"""Identity generation.

Every identity in engram is a UUIDv7: globally unique, time-ordered (index-friendly
in SQLite), and immutable once assigned. Filenames and slugs are projections of
identity, never identity itself (ADR-0003).
"""

from uuid import UUID

import uuid6


def new_uuid7() -> UUID:
    """Return a new time-ordered UUIDv7."""
    return uuid6.uuid7()
