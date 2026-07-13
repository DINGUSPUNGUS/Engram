"""The export manifest: counts, per-file checksums, and a Merkle-style root.

The manifest is the export's integrity contract. Every content file gets a
deterministic sha256; the ``merkle_root`` summarizes the whole tree, so two
exports are byte-equivalent iff their roots match — future sync rides on this.

Determinism rule: the volatile fields (``generated_at``, ``duration_ms``) are
refreshed only when content actually changed; an export that changes nothing
leaves the manifest untouched, keeping repeated exports byte-identical.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from engram_core.domain.errors import ValidationError

MANIFEST_SCHEMA_VERSION = 1
EXPORT_FORMAT_VERSION = 1


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def merkle_root(files: Mapping[str, str]) -> str:
    """Root hash over the sorted ``path<space>digest`` lines.

    Not a full Merkle tree yet — a single-level digest-of-digests. The name marks
    the contract (a content-addressed summary future sync can diff against); the
    tree shape can deepen without changing callers.
    """
    lines = "\n".join(f"{path} {digest}" for path, digest in sorted(files.items()))
    return sha256_hex(lines.encode("utf-8"))


@dataclass(frozen=True, slots=True)
class Manifest:
    manifest_schema_version: int
    export_format_version: int
    engine_version: str
    engine_git_commit: str | None
    generated_at: str
    duration_ms: int
    head_global_seq: int
    counts: dict[str, int] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    merkle_root: str = ""

    def content_equal(self, other: "Manifest | None") -> bool:
        """True when the *content* (not the volatile metadata) is unchanged."""
        return other is not None and (
            self.files == other.files
            and self.merkle_root == other.merkle_root
            and self.counts == other.counts
            and self.head_global_seq == other.head_global_seq
            and self.export_format_version == other.export_format_version
        )

    def to_json(self) -> str:
        record: dict[str, Any] = {
            "manifest_schema_version": self.manifest_schema_version,
            "export_format_version": self.export_format_version,
            "engine_version": self.engine_version,
            "engine_git_commit": self.engine_git_commit,
            "generated_at": self.generated_at,
            "duration_ms": self.duration_ms,
            "head_global_seq": self.head_global_seq,
            "counts": dict(sorted(self.counts.items())),
            "files": dict(sorted(self.files.items())),
            "merkle_root": self.merkle_root,
        }
        return json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def parse_manifest(text: str) -> Manifest:
    """Parse and version-check a manifest.

    Raises:
        ValidationError: not JSON, missing fields, or a schema version this
            engine does not understand (newer than it can read).
    """
    try:
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"manifest is not valid JSON: {exc}") from exc
    if not isinstance(record, dict):
        raise ValidationError("manifest must be a JSON object")
    version = record.get("manifest_schema_version")
    if not isinstance(version, int) or version < 1:
        raise ValidationError(f"manifest_schema_version missing or invalid: {version!r}")
    if version > MANIFEST_SCHEMA_VERSION:
        raise ValidationError(
            f"manifest schema version {version} is newer than this engine understands"
            f" ({MANIFEST_SCHEMA_VERSION}) — upgrade engram to import this export"
        )
    try:
        return Manifest(
            manifest_schema_version=version,
            export_format_version=int(record["export_format_version"]),
            engine_version=str(record["engine_version"]),
            engine_git_commit=record.get("engine_git_commit"),
            generated_at=str(record["generated_at"]),
            duration_ms=int(record["duration_ms"]),
            head_global_seq=int(record["head_global_seq"]),
            counts={str(k): int(v) for k, v in dict(record["counts"]).items()},
            files={str(k): str(v) for k, v in dict(record["files"]).items()},
            merkle_root=str(record["merkle_root"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError(f"malformed manifest: {exc!r}") from exc


def verify_files(files: Mapping[str, str], read_bytes: Mapping[str, bytes]) -> list[str]:
    """Return the paths whose checksum does not match (empty = intact)."""
    mismatched = [
        path
        for path, digest in files.items()
        if path not in read_bytes or sha256_hex(read_bytes[path]) != digest
    ]
    mismatched.extend(path for path in read_bytes if path not in files)
    return sorted(mismatched)
