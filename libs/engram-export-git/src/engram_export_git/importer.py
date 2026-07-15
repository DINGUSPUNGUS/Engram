"""The import engine: exported repositories → proposals (or a verbatim restore).

Two operations with deliberately different trust models (ADR-0017):

- **Restore** reconstitutes the event log from ``timeline/events.ndjson`` into an
  **empty** space. It is not an import — the events were already decided once;
  replaying them is disaster recovery / machine migration, and it refuses to run
  if the space contains any events at all.
- **Import** reads memory documents (markdown or memories.ndjson) as *candidate
  knowledge*: everything is validated (schema, UUIDs, relationships, evidence,
  timestamps), and the result is a **Proposal** carrying draft events. Nothing
  imported bypasses the proposal system (ADR-0011) — a human approves and merges
  (M4) before any memory changes.

Validation is all-or-nothing per run: every problem in every file is collected
and reported together; nothing is written unless everything passes.
"""

import dataclasses
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from engram_core.application.commands import drafts as d
from engram_core.application.commands.proposal_commands import ProposalCommandService
from engram_core.domain.errors import ConflictError, ValidationError
from engram_core.domain.kinds import KindRegistry
from engram_core.domain.memory import Memory
from engram_core.domain.values import (
    EvidenceType,
    LinkRelation,
    MemoryKind,
    ProposalId,
    RetentionPolicy,
    Slug,
    Visibility,
    validate_confidence,
)
from engram_events import EventEnvelope, EventRegistry, EventStore, Provenance, new_uuid7
from engram_events.serde import encode_json_value
from engram_export_git import layout, ndjson
from engram_export_git.exporter import iter_ndjson_lines
from engram_export_git.frontmatter import ParsedDocument, parse_document
from engram_export_git.manifest import parse_manifest, sha256_hex

_RESTORE_BATCH = 500


@dataclass(frozen=True, slots=True)
class RestoreReport:
    events: int
    streams: int


@dataclass(frozen=True, slots=True)
class ImportReport:
    """What one import run proposed. ``memories`` = created + edited.

    ``proposal_id`` is None when every document matched current state exactly —
    nothing to review, nothing opened."""

    proposal_id: ProposalId | None
    memories: int
    links: int
    evidence: int
    created: int = 0
    edited: int = 0
    unchanged: int = 0


class ImportEngine:
    """Validated ingestion of exported repositories."""

    def __init__(
        self,
        store: EventStore,
        registry: EventRegistry,
        kinds: KindRegistry,
        proposals: ProposalCommandService,
    ) -> None:
        self._store = store
        self._registry = registry
        self._kinds = kinds
        self._proposals = proposals

    # -- restore (the lossless round-trip path) ---------------------------------

    def restore(self, source: Path) -> RestoreReport:
        """Rebuild the event log verbatim from an export. Empty spaces only.

        ``source`` is an export repository root or an events NDJSON file. When a
        manifest is present, the event file's checksum is verified first.

        Raises:
            ValidationError: malformed records, checksum mismatch, or broken
                stream/global ordering.
            ConflictError: the target space already contains events.
        """
        events_file = self._locate_events_file(source)
        if self._store.read_all(after_global_seq=0, limit=1):
            raise ConflictError(
                "restore refuses to run on a non-empty space — it reconstitutes"
                " history, it does not merge; use `engram import` for that"
            )
        envelopes = self._parse_event_file(events_file)
        self._validate_ordering(envelopes)
        streams = {envelope.stream_id for envelope in envelopes}
        for start in range(0, len(envelopes), _RESTORE_BATCH):
            batch = [
                # global_seq is the store's to assign; everything else is preserved.
                _without_global_seq(envelope)
                for envelope in envelopes[start : start + _RESTORE_BATCH]
            ]
            self._store.append(batch)
        return RestoreReport(events=len(envelopes), streams=len(streams))

    def _locate_events_file(self, source: Path) -> Path:
        if source.is_file():
            return source
        events_path = layout.resolve_inside(source, layout.EVENTS_PATH)
        manifest_path = layout.resolve_inside(source, layout.MANIFEST_PATH)
        if not events_path.exists():
            raise ValidationError(f"no event log found at {events_path}")
        if manifest_path.exists():
            manifest = parse_manifest(manifest_path.read_text(encoding="utf-8"))
            recorded = manifest.files.get(str(layout.EVENTS_PATH))
            actual = sha256_hex(events_path.read_bytes())
            if recorded is not None and recorded != actual:
                raise ValidationError(
                    "event log checksum does not match the manifest — the export is"
                    f" corrupt or was edited ({actual} != {recorded})"
                )
        return events_path

    def _parse_event_file(self, events_file: Path) -> list[EventEnvelope]:
        envelopes: list[EventEnvelope] = []
        errors: list[str] = []
        for line_no, line in enumerate(iter_ndjson_lines(events_file.read_bytes()), start=1):
            try:
                record = _parse_json_line(line)
                envelopes.append(ndjson.record_to_envelope(self._registry, record))
            except ValidationError as exc:
                errors.append(f"line {line_no}: {exc}")
        if errors:
            raise ValidationError("event log is malformed:\n" + "\n".join(errors))
        if not envelopes:
            raise ValidationError("event log is empty — nothing to restore")
        return envelopes

    @staticmethod
    def _validate_ordering(envelopes: Sequence[EventEnvelope]) -> None:
        errors: list[str] = []
        previous_global = 0
        next_expected: dict[UUID, int] = {}
        for envelope in envelopes:
            if envelope.global_seq is None or envelope.global_seq <= previous_global:
                errors.append(
                    f"event {envelope.event_id}: global_seq {envelope.global_seq}"
                    " is not strictly increasing"
                )
            else:
                previous_global = envelope.global_seq
            expected = next_expected.get(envelope.stream_id, 1)
            if envelope.stream_seq != expected:
                errors.append(
                    f"stream {envelope.stream_id}: expected stream_seq {expected},"
                    f" got {envelope.stream_seq}"
                )
            next_expected[envelope.stream_id] = envelope.stream_seq + 1
        if errors:
            raise ValidationError("event log ordering is broken:\n" + "\n".join(errors))

    # -- import (external knowledge → proposals) ---------------------------------

    def import_documents(
        self, source: Path, provenance: Provenance, *, title: str | None = None
    ) -> ImportReport:
        """Validate memory documents and open ONE proposal carrying draft intents.

        Documents whose ``id`` already exists in the store are **reconciled**
        (ADR-0018 §4): the current aggregate is folded from its stream, the
        semantic difference is computed, and edit intents are proposed — never a
        duplicate ``MemoryCreated``. Unchanged documents contribute nothing; a
        fully-unchanged import opens no proposal.

        ``source`` may be an export repository root, a directory of markdown, a
        single ``.md`` file, or a ``.ndjson`` file of memory records.

        Raises:
            ValidationError: any invalid document, or a document addressing a
                tombstoned memory (all problems reported at once); nothing is
                opened on failure.
        """
        candidates, errors = self._collect_candidates(source)
        if not errors and not candidates:
            raise ValidationError(f"nothing importable found at {source}")

        intents: list[d.DraftIntent] = []
        created = edited = unchanged = links = evidence = 0
        for candidate in candidates:
            current, problem = self._load_existing(candidate)
            if problem is not None:
                errors.append(problem)
                continue
            if current is None:
                batch = _create_intents(candidate)
                created += 1
            else:
                batch = _reconcile_intents(candidate, current)
                if batch:
                    edited += 1
                else:
                    unchanged += 1
            links += sum(isinstance(i, d.LinkDraft | d.UnlinkDraft) for i in batch)
            evidence += sum(isinstance(i, d.AddEvidenceDraft) for i in batch)
            intents.extend(batch)
        if errors:
            raise ValidationError("import rejected:\n" + "\n".join(errors))

        if not intents:
            return ImportReport(
                proposal_id=None, memories=0, links=0, evidence=0, unchanged=unchanged
            )
        proposal_id = self._proposals.open_proposal(
            title or f"import: {source.name}",
            f"imported from {source} ({created} new, {edited} edited, {unchanged} unchanged)",
            [d.to_dict(intent) for intent in intents],
            provenance,
        )
        return ImportReport(
            proposal_id=proposal_id,
            memories=created + edited,
            links=links,
            evidence=evidence,
            created=created,
            edited=edited,
            unchanged=unchanged,
        )

    def _load_existing(self, candidate: dict[str, Any]) -> tuple[Memory | None, str | None]:
        """The current aggregate for this candidate's id, if the stream exists."""
        envelopes = self._store.read_stream(UUID(candidate["id"]))
        if not envelopes:
            return None, None
        memory = Memory.fold(list(envelopes), self._kinds)
        if memory.deleted:
            return None, (
                f"{candidate['name']}: memory {candidate['id']} was deleted;"
                " re-importing it would resurrect history — use a new id instead"
            )
        if memory.kind.value != candidate["created"]["kind"]:
            return None, (
                f"{candidate['name']}: kind mismatch for {candidate['id']}"
                f" (file says {candidate['created']['kind']},"
                f" the memory is {memory.kind.value}; kind is immutable)"
            )
        return memory, None

    # -- candidate collection -----------------------------------------------------

    def _collect_candidates(self, source: Path) -> tuple[list[dict[str, Any]], list[str]]:
        documents: list[tuple[str, ParsedDocument]] = []
        ndjson_records: list[tuple[str, dict[str, Any]]] = []
        errors: list[str] = []

        if source.is_file() and source.suffix == ".md":
            self._read_markdown(source, source.name, documents, errors)
        elif source.is_file() and source.suffix == ".ndjson":
            self._read_ndjson(source, source.name, ndjson_records, errors)
        elif source.is_dir():
            markdown_root = (
                source / str(layout.MEMORY_DIR)
                if (source / str(layout.MEMORY_DIR)).exists()
                else source
            )
            for path in sorted(markdown_root.rglob("*.md")):
                if path.name == "README.md":
                    continue
                self._read_markdown(path, str(path.relative_to(source)), documents, errors)
            memories_ndjson = source / str(layout.MEMORIES_NDJSON_PATH)
            if not documents and memories_ndjson.exists():
                self._read_ndjson(memories_ndjson, str(memories_ndjson), ndjson_records, errors)
        else:
            errors.append(f"unsupported import source: {source}")

        candidates: list[dict[str, Any]] = []
        seen_ids: dict[str, str] = {}
        all_ids = _collect_ids(documents, ndjson_records)
        for name, document in documents:
            self._validate_candidate(
                name,
                {**document.meta, "content": document.body, "evidence": list(document.evidence)},
                all_ids,
                seen_ids,
                candidates,
                errors,
            )
        for name, record in ndjson_records:
            self._validate_candidate(name, record, all_ids, seen_ids, candidates, errors)
        return candidates, errors

    def _read_markdown(
        self,
        path: Path,
        name: str,
        documents: list[tuple[str, ParsedDocument]],
        errors: list[str],
    ) -> None:
        try:
            # utf-8-sig: Windows editors love BOMs; a BOM must not hide the frontmatter.
            documents.append((name, parse_document(path.read_text(encoding="utf-8-sig"))))
        except (ValidationError, UnicodeDecodeError) as exc:
            errors.append(f"{name}: {exc}")

    def _read_ndjson(
        self,
        path: Path,
        name: str,
        records: list[tuple[str, dict[str, Any]]],
        errors: list[str],
    ) -> None:
        for line_no, line in enumerate(iter_ndjson_lines(path.read_bytes()), start=1):
            try:
                record = _parse_json_line(line)
                version = record.get("record_schema_version")
                if version != ndjson.MEMORY_RECORD_SCHEMA_VERSION:
                    raise ValidationError(f"unsupported memory record schema version: {version!r}")
                records.append((f"{name}:{line_no}", record))
            except ValidationError as exc:
                errors.append(f"{name}:{line_no}: {exc}")

    def _validate_candidate(
        self,
        name: str,
        raw: dict[str, Any],
        all_ids: set[str],
        seen_ids: dict[str, str],
        candidates: list[dict[str, Any]],
        errors: list[str],
    ) -> None:
        problems: list[str] = []

        def fail(message: str) -> None:
            problems.append(f"{name}: {message}")

        memory_id = _validated_uuid(raw.get("id"), fail, minted_ok=True)
        if memory_id is not None:
            if str(memory_id) in seen_ids:
                fail(f"duplicate id {memory_id} (also in {seen_ids[str(memory_id)]})")
            else:
                seen_ids[str(memory_id)] = name

        kind: MemoryKind | None = None
        try:
            kind = MemoryKind(str(raw.get("kind", "")))
        except ValueError:
            fail(f"unknown kind: {raw.get('kind')!r}")

        title = str(raw.get("title") or "")
        if not title.strip():
            fail("title is missing or empty")
        slug_value = raw.get("slug")
        slug: str | None = None
        if slug_value is not None:
            try:
                slug = str(Slug(str(slug_value)))
            except ValidationError as exc:
                fail(str(exc))

        attributes = raw.get("attributes") or {}
        if kind is not None and isinstance(attributes, dict):
            try:
                self._kinds.parse(
                    kind, dict(attributes), schema_version=int(raw.get("schema_version", 1))
                )
            except ValidationError as exc:
                fail(f"attributes do not match the {kind.value} schema: {exc}")
        elif not isinstance(attributes, dict):
            fail("attributes must be a mapping")

        confidence = raw.get("confidence", 0.6)
        try:
            confidence = validate_confidence(float(confidence))
        except (TypeError, ValueError, ValidationError):
            fail(f"confidence must be a number in [0,1], got {confidence!r}")
            confidence = 0.6

        visibility = str(raw.get("visibility", "shared"))
        if visibility not in set(Visibility):
            fail(f"unknown visibility: {visibility!r}")
        lifetime = str(raw.get("lifetime", "standard"))
        if lifetime not in set(RetentionPolicy):
            fail(f"unknown lifetime policy: {lifetime!r}")
        lifetime_until = raw.get("lifetime_until")
        if (lifetime == "until") != (lifetime_until is not None):
            fail("lifetime 'until' requires lifetime_until, other policies forbid it")

        for stamp_key in ("created_at", "updated_at"):
            stamp = raw.get(stamp_key)
            if stamp is not None and _parse_timestamp(stamp) is None:
                fail(f"{stamp_key} is not a valid ISO-8601 timestamp: {stamp!r}")

        tags = raw.get("tags") or []
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            fail("tags must be a list of strings")
            tags = []

        links: list[dict[str, object]] = []
        for entry in raw.get("links") or []:
            if not isinstance(entry, dict):
                fail(f"link entries must be mappings, got {entry!r}")
                continue
            relation = str(entry.get("relation", ""))
            if relation not in set(LinkRelation):
                fail(f"unknown link relation: {relation!r}")
                continue
            target = _validated_uuid(entry.get("target") or entry.get("target_id"), fail)
            if target is None:
                continue
            if str(target) not in all_ids and not self._store.read_stream(target):
                fail(f"link target {target} is neither in this import nor in the store")
                continue
            links.append({"target_id": str(target), "relation": relation})

        evidence_payloads: list[dict[str, object]] = []
        for entry in raw.get("evidence") or []:
            if not isinstance(entry, dict):
                fail(f"evidence entries must be mappings, got {entry!r}")
                continue
            evidence_type = str(entry.get("type", ""))
            if evidence_type not in set(EvidenceType):
                fail(f"unknown evidence type: {evidence_type!r}")
                continue
            value = entry.get("value")
            if not isinstance(value, str) or not value.strip():
                fail("evidence value must be a non-empty string")
                continue
            note = entry.get("note")
            evidence_payloads.append(
                {
                    "evidence_type": evidence_type,
                    "value": value,
                    "note": str(note) if note is not None else None,
                }
            )

        if problems:
            errors.extend(problems)
            return

        assert kind is not None and memory_id is not None
        resolved_slug = slug or str(Slug(f"imported-{memory_id.hex[:8]}"))
        candidates.append(
            {
                "id": str(memory_id),
                "name": name,
                "links": links,
                "evidence": evidence_payloads,
                # Absent keys must not be diffed against existing memories: a
                # hand-written partial document is not a request to remove things.
                "specified": {
                    "slug": slug is not None,
                    "tags": "tags" in raw,
                    "links": "links" in raw,
                    "visibility": "visibility" in raw,
                    "lifetime": "lifetime" in raw,
                },
                "created": {
                    "memory_id": str(memory_id),
                    "kind": kind.value,
                    "slug": resolved_slug,
                    "title": title.strip(),
                    "content": str(raw.get("content") or ""),
                    "attributes": dict(attributes),
                    "attributes_schema_version": int(raw.get("schema_version", 1)),
                    "tags": sorted({tag.strip().lower() for tag in tags if tag.strip()}),
                    "confidence": confidence,
                    "lifetime_policy": lifetime,
                    "lifetime_until": str(lifetime_until) if lifetime_until else None,
                    "visibility": visibility,
                },
            }
        )


# -- helpers --------------------------------------------------------------------


def _parse_json_line(line: str) -> dict[str, Any]:
    try:
        record = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"not valid JSON: {exc}") from exc
    if not isinstance(record, dict):
        raise ValidationError("each NDJSON line must be a JSON object")
    return record


def _collect_ids(
    documents: list[tuple[str, ParsedDocument]],
    records: list[tuple[str, dict[str, Any]]],
) -> set[str]:
    ids: set[str] = set()
    for _, document in documents:
        value = document.meta.get("id")
        if isinstance(value, str):
            ids.add(value.lower())
    for _, record in records:
        value = record.get("id")
        if isinstance(value, str):
            ids.add(value.lower())
    return ids


def _validated_uuid(value: object, fail: Any, *, minted_ok: bool = False) -> UUID | None:
    if value is None and minted_ok:
        return new_uuid7()  # hand-written files may omit id; identity is minted (ADR-0003)
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        fail(f"invalid UUID: {value!r}")
        return None


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _create_intents(candidate: dict[str, Any]) -> list[d.DraftIntent]:
    """A brand-new memory: one create + its links + its evidence."""
    created = candidate["created"]
    memory_id = UUID(candidate["id"])
    intents: list[d.DraftIntent] = [
        d.CreateMemoryDraft(
            memory_id=memory_id,
            kind=created["kind"],
            slug=created["slug"],
            title=created["title"],
            content=created["content"],
            attributes=dict(created["attributes"]),
            attributes_schema_version=created["attributes_schema_version"],
            tags=tuple(created["tags"]),
            confidence=created["confidence"],
            lifetime_policy=created["lifetime_policy"],
            lifetime_until=created["lifetime_until"],
            visibility=created["visibility"],
            base_version=0,
        )
    ]
    for link in candidate["links"]:
        intents.append(
            d.LinkDraft(
                source_id=memory_id,
                target_id=UUID(str(link["target_id"])),
                relation=str(link["relation"]),
                base_version=None,  # same-proposal follow-up on a stream created above
            )
        )
    for entry in candidate["evidence"]:
        intents.append(
            d.AddEvidenceDraft(
                memory_id=memory_id,
                base_version=None,
                evidence_type=str(entry["evidence_type"]),
                value=str(entry["value"]),
                note=entry["note"],
            )
        )
    return intents


def _reconcile_intents(candidate: dict[str, Any], memory: Memory) -> list[d.DraftIntent]:
    """The semantic difference between a document and the current aggregate,
    expressed as edit intents (ADR-0018 §4). Empty when nothing differs."""
    created = candidate["created"]
    specified = candidate["specified"]
    memory_id = UUID(candidate["id"])
    base = memory.version
    intents: list[d.DraftIntent] = []

    new_title = created["title"] if created["title"] != memory.title else None
    new_content = (
        created["content"] if created["content"].rstrip() != memory.content.rstrip() else None
    )
    new_slug = (
        created["slug"] if specified["slug"] and created["slug"] != str(memory.slug) else None
    )
    if new_title is not None or new_content is not None or new_slug is not None:
        intents.append(
            d.EditMemoryDraft(
                memory_id=memory_id,
                base_version=base,
                title=new_title,
                content=new_content,
                slug=new_slug,
            )
        )

    if specified["tags"]:
        file_tags = set(created["tags"])
        current_tags = set(memory.tags)
        add = tuple(sorted(file_tags - current_tags))
        remove = tuple(sorted(current_tags - file_tags))
        if add or remove:
            intents.append(
                d.TagMemoryDraft(memory_id=memory_id, base_version=base, add=add, remove=remove)
            )

    current_attributes = dataclasses.asdict(memory.attributes)
    changes = {
        key: value
        for key, value in created["attributes"].items()
        if key in current_attributes
        and encode_json_value(current_attributes[key]) != encode_json_value(value)
    }
    if changes:
        intents.append(
            d.UpdateAttributesDraft(memory_id=memory_id, base_version=base, changes=changes)
        )

    if specified["links"]:
        file_links = {
            (str(link["relation"]), str(link["target_id"])) for link in candidate["links"]
        }
        current_links = {(link.relation.value, str(link.target_id)) for link in memory.links}
        for relation, target in sorted(file_links - current_links):
            intents.append(
                d.LinkDraft(
                    source_id=memory_id,
                    target_id=UUID(target),
                    relation=relation,
                    base_version=base,
                )
            )
        for relation, target in sorted(current_links - file_links):
            intents.append(
                d.UnlinkDraft(
                    source_id=memory_id,
                    target_id=UUID(target),
                    relation=relation,
                    base_version=base,
                )
            )

    current_evidence = {(ref.evidence_type.value, ref.value, ref.note) for ref in memory.evidence}
    for entry in candidate["evidence"]:
        key = (str(entry["evidence_type"]), str(entry["value"]), entry["note"])
        if key not in current_evidence:
            intents.append(
                d.AddEvidenceDraft(
                    memory_id=memory_id,
                    base_version=base,
                    evidence_type=str(entry["evidence_type"]),
                    value=str(entry["value"]),
                    note=entry["note"],
                )
            )
    # Evidence *removals* in the file are deliberately ignored: retraction is a
    # reviewed action (undo), not a file edit (ADR-0018 §4).

    if specified["visibility"] and created["visibility"] != memory.visibility.value:
        intents.append(
            d.SetVisibilityDraft(
                memory_id=memory_id, base_version=base, visibility=created["visibility"]
            )
        )
    if specified["lifetime"] and (
        created["lifetime_policy"] != memory.lifetime.policy.value
        or created["lifetime_until"] != encode_json_value(memory.lifetime.until)
    ):
        intents.append(
            d.SetLifetimeDraft(
                memory_id=memory_id,
                base_version=base,
                lifetime_policy=created["lifetime_policy"],
                lifetime_until=created["lifetime_until"],
            )
        )
    # Confidence changes are deliberately not diffed: confidence moves through
    # confirmation/contradiction (the scoring spine), not file edits.
    return intents


def _without_global_seq(envelope: EventEnvelope) -> EventEnvelope:
    return dataclasses.replace(envelope, global_seq=None)
