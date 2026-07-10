"""Event type registry.

Maps event type names to payload dataclasses and holds upcasters — functions that
migrate a payload dict from one schema version to the next. Registration happens at
import time in the package that owns the event (domain events live in engram-core).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

Upcaster = Callable[[dict[str, Any]], dict[str, Any]]
"""Migrates a payload dict from version N to version N+1."""


class EventTypeAlreadyRegisteredError(Exception):
    """Raised when two payload types claim the same event type name."""


class UnknownEventTypeError(Exception):
    """Raised when an event type name has no registration."""


@dataclass
class _Registration:
    payload_type: type
    schema_version: int
    upcasters: dict[int, Upcaster] = field(default_factory=dict)


class EventRegistry:
    """Registry of event types, their payload classes, and their upcasters."""

    def __init__(self) -> None:
        self._registrations: dict[str, _Registration] = {}

    def register(self, event_type: str, payload_type: type, *, schema_version: int = 1) -> None:
        """Register ``payload_type`` as the payload for ``event_type``.

        Raises:
            EventTypeAlreadyRegisteredError: if the name is already taken.
        """
        if event_type in self._registrations:
            raise EventTypeAlreadyRegisteredError(event_type)
        self._registrations[event_type] = _Registration(payload_type, schema_version)

    def register_upcaster(self, event_type: str, from_version: int, upcaster: Upcaster) -> None:
        """Register a migration from ``from_version`` to ``from_version + 1``."""
        self._registration(event_type).upcasters[from_version] = upcaster

    def payload_type(self, event_type: str) -> type:
        """Return the payload dataclass registered for ``event_type``."""
        return self._registration(event_type).payload_type

    def current_version(self, event_type: str) -> int:
        """Return the current (write-side) schema version for ``event_type``."""
        return self._registration(event_type).schema_version

    def upcast(self, event_type: str, data: dict[str, Any], from_version: int) -> dict[str, Any]:
        """Migrate ``data`` from ``from_version`` up to the current schema version."""
        registration = self._registration(event_type)
        version = from_version
        while version < registration.schema_version:
            upcaster = registration.upcasters.get(version)
            if upcaster is None:
                raise UnknownEventTypeError(
                    f"{event_type}: no upcaster from schema_version {version}"
                )
            data = upcaster(data)
            version += 1
        return data

    def registered_types(self) -> Mapping[str, type]:
        """Return a read-only view of all registered event types."""
        return {name: reg.payload_type for name, reg in self._registrations.items()}

    def _registration(self, event_type: str) -> _Registration:
        try:
            return self._registrations[event_type]
        except KeyError:
            raise UnknownEventTypeError(event_type) from None
