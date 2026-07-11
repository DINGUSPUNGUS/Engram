"""Kind schemas: the shape of each of the twelve memory kinds (ADR-0008).

One frozen dataclass per kind, versioned in the KindRegistry exactly like event
payloads are versioned in the event registry: shipped shapes never change in place —
bump ``schema_version`` and register an upcaster so historical attributes parse
forever. Closed vocabularies are StrEnums; extending one is a schema version bump.

Attributes are the *queryable* truth; the memory's markdown ``content`` remains the
human narrative around them (memory-model.md §1).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from engram_core.domain.errors import ValidationError
from engram_core.domain.values import MemoryKind

# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------


class PreferencePolarity(StrEnum):
    LIKES = "likes"
    DISLIKES = "dislikes"
    WANTS = "wants"
    AVOIDS = "avoids"
    PREFERS = "prefers"


class OrgType(StrEnum):
    COMPANY = "company"
    TEAM = "team"
    COMMUNITY = "community"
    INSTITUTION = "institution"
    OTHER = "other"


class ProjectStatus(StrEnum):
    IDEA = "idea"
    ACTIVE = "active"
    PAUSED = "paused"
    DONE = "done"
    ABANDONED = "abandoned"


class Proficiency(StrEnum):
    NOVICE = "novice"
    COMPETENT = "competent"
    PROFICIENT = "proficient"
    EXPERT = "expert"


class GoalHorizon(StrEnum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class GoalStatus(StrEnum):
    ACTIVE = "active"
    ACHIEVED = "achieved"
    DROPPED = "dropped"


class ContactChannel(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    HANDLE = "handle"
    ADDRESS = "address"
    OTHER = "other"


class LocationType(StrEnum):
    HOME = "home"
    WORK = "work"
    CITY = "city"
    VENUE = "venue"
    OTHER = "other"


class AssetType(StrEnum):
    FILE = "file"
    DOCUMENT = "document"
    DEVICE = "device"
    ACCOUNT = "account"
    DOMAIN = "domain"
    REPOSITORY = "repository"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Attribute schemas, v1 (memory-model.md §2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FactAttributes:
    statement: str


@dataclass(frozen=True, slots=True)
class PreferenceAttributes:
    polarity: PreferencePolarity
    strength: float | None = None  # 0..1
    context: str | None = None  # e.g. "food", "code-style"


@dataclass(frozen=True, slots=True)
class PersonAttributes:
    full_name: str
    aliases: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    notes: str | None = None
    # Affiliations are works_at edges; contact info is contact memories (owned_by).


@dataclass(frozen=True, slots=True)
class OrganizationAttributes:
    name: str
    aliases: tuple[str, ...] = ()
    org_type: OrgType | None = None
    url: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectAttributes:
    name: str
    status: ProjectStatus
    summary: str | None = None
    target_date: datetime | None = None
    # Participants are involves edges; related memories are inbound about edges.


@dataclass(frozen=True, slots=True)
class SkillAttributes:
    name: str
    proficiency: Proficiency | None = None
    last_used_at: datetime | None = None
    # Proficiency evidence lives in the spine's evidence list.


@dataclass(frozen=True, slots=True)
class GoalAttributes:
    statement: str
    status: GoalStatus
    horizon: GoalHorizon | None = None
    target_date: datetime | None = None
    # Hierarchy is part_of edges.


@dataclass(frozen=True, slots=True)
class ContactAttributes:
    channel: ContactChannel
    value: str
    label: str | None = None  # "work", "personal"
    preferred: bool = False
    # Always linked owned_by -> person|organization.


@dataclass(frozen=True, slots=True)
class EventAttributes:
    occurred_at: datetime
    end_at: datetime | None = None
    outcome: str | None = None
    # Participants are involves edges; place is located_in.


@dataclass(frozen=True, slots=True)
class LocationAttributes:
    name: str
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    location_type: LocationType | None = None


@dataclass(frozen=True, slots=True)
class AssetAttributes:
    asset_type: AssetType
    uri: str | None = None
    identifier: str | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class RelationshipAttributes:
    """The reified tier-2 edge (ADR-0010): a connection that is itself knowledge."""

    subject_id: UUID
    predicate: str
    object_id: UUID
    since: datetime | None = None
    until: datetime | None = None


KindAttributes = (
    FactAttributes
    | PreferenceAttributes
    | PersonAttributes
    | OrganizationAttributes
    | ProjectAttributes
    | SkillAttributes
    | GoalAttributes
    | ContactAttributes
    | EventAttributes
    | LocationAttributes
    | AssetAttributes
    | RelationshipAttributes
)


# ---------------------------------------------------------------------------
# Registry (mirrors the event registry: versions + upcasters)
# ---------------------------------------------------------------------------

AttributesUpcaster = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass
class _KindRegistration:
    attributes_type: type
    schema_version: int
    upcasters: dict[int, AttributesUpcaster] = field(default_factory=dict)


class KindRegistry:
    """Versioned attribute schemas per kind. Shipped shapes never change in place."""

    def __init__(self) -> None:
        self._registrations: dict[MemoryKind, _KindRegistration] = {}

    def register(self, kind: MemoryKind, attributes_type: type, *, schema_version: int = 1) -> None:
        if kind in self._registrations:
            raise ValidationError(f"kind already registered: {kind}")
        self._registrations[kind] = _KindRegistration(attributes_type, schema_version)

    def register_upcaster(
        self, kind: MemoryKind, from_version: int, upcaster: AttributesUpcaster
    ) -> None:
        self._registration(kind).upcasters[from_version] = upcaster

    def attributes_type(self, kind: MemoryKind) -> type:
        return self._registration(kind).attributes_type

    def current_version(self, kind: MemoryKind) -> int:
        return self._registration(kind).schema_version

    def upcast(self, kind: MemoryKind, data: dict[str, Any], from_version: int) -> dict[str, Any]:
        registration = self._registration(kind)
        version = from_version
        while version < registration.schema_version:
            upcaster = registration.upcasters.get(version)
            if upcaster is None:
                raise ValidationError(f"{kind}: no attributes upcaster from v{version}")
            data = upcaster(data)
            version += 1
        return data

    def registered_kinds(self) -> Mapping[MemoryKind, type]:
        return {kind: reg.attributes_type for kind, reg in self._registrations.items()}

    def parse(
        self, kind: MemoryKind, data: dict[str, Any], *, schema_version: int
    ) -> KindAttributes:
        """Rehydrate stored attributes (any historical version) into the current schema.

        Raises:
            ValidationError: unknown kind, missing upcaster, or shape mismatch.
        """
        migrated = self.upcast(kind, dict(data), schema_version)
        attributes_type = self.attributes_type(kind)
        try:
            return attributes_type(**migrated)  # type: ignore[no-any-return]
        except TypeError as exc:
            raise ValidationError(f"invalid {kind} attributes: {exc}") from exc

    def _registration(self, kind: MemoryKind) -> _KindRegistration:
        try:
            return self._registrations[kind]
        except KeyError:
            raise ValidationError(f"unregistered kind: {kind}") from None


_KIND_SCHEMAS: dict[MemoryKind, type] = {
    MemoryKind.FACT: FactAttributes,
    MemoryKind.PREFERENCE: PreferenceAttributes,
    MemoryKind.PERSON: PersonAttributes,
    MemoryKind.ORGANIZATION: OrganizationAttributes,
    MemoryKind.PROJECT: ProjectAttributes,
    MemoryKind.SKILL: SkillAttributes,
    MemoryKind.GOAL: GoalAttributes,
    MemoryKind.CONTACT: ContactAttributes,
    MemoryKind.EVENT: EventAttributes,
    MemoryKind.LOCATION: LocationAttributes,
    MemoryKind.ASSET: AssetAttributes,
    MemoryKind.RELATIONSHIP: RelationshipAttributes,
}


def build_kind_registry() -> KindRegistry:
    """Build the canonical kind registry. All schemas start at version 1."""
    registry = KindRegistry()
    for kind, attributes_type in _KIND_SCHEMAS.items():
        registry.register(kind, attributes_type, schema_version=1)
    return registry
