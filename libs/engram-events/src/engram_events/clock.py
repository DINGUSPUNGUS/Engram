"""The default wall clock. Matches engram-core's ``Clock`` protocol structurally
(the kernel deliberately does not import the protocol)."""

from datetime import UTC, datetime


class SystemClock:
    """Timezone-aware UTC now."""

    def now(self) -> datetime:
        return datetime.now(UTC)
