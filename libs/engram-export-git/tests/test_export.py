"""Export contract: deterministic bytes, honest manifest, verifiable checksums."""

from pathlib import Path

import pytest
from export_harness import USER, Space

from engram_core.application.dto import EditMemoryInput
from engram_core.domain.errors import ValidationError
from engram_core.domain.values import MemoryId
from engram_export_git import layout
from engram_export_git.manifest import merkle_root, parse_manifest, sha256_hex, verify_files


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.parts
    }


def _content_files(tree: dict[str, bytes]) -> dict[str, bytes]:
    return {path: data for path, data in tree.items() if path != "manifest.json"}


@pytest.mark.integration
class TestDeterminism:
    def test_repeated_export_is_byte_identical_and_touches_nothing(
        self, space: Space, seeded: dict[str, MemoryId], tmp_path: Path
    ) -> None:
        root = tmp_path / "repo"
        first = space.exporter.export(root)
        assert first.changed
        snapshot = _tree(root)

        second = space.exporter.export(root)
        assert not second.changed
        assert second.written == ()
        assert _tree(root) == snapshot  # manifest included: bytes frozen

    def test_two_spaces_with_same_history_export_same_content_hash(
        self, space: Space, seeded: dict[str, MemoryId], tmp_path: Path
    ) -> None:
        root_a = tmp_path / "a"
        report_a = space.exporter.export(root_a)
        # Restore into a fresh space, then export it — same merkle root.
        from export_harness import build_space

        other = build_space(tmp_path / "other.db")
        other.importer.restore(root_a)
        other.rebuild()
        report_b = other.exporter.export(tmp_path / "b")
        assert report_b.manifest.merkle_root == report_a.manifest.merkle_root

    def test_stable_ordering_in_ndjson(
        self, space: Space, seeded: dict[str, MemoryId], tmp_path: Path
    ) -> None:
        space.exporter.export(tmp_path / "repo")
        events = (tmp_path / "repo" / "timeline" / "events.ndjson").read_text("utf-8")
        seqs = [line.index('"global_seq"') >= 0 for line in events.splitlines()]
        assert all(seqs)
        import json

        globals_ = [json.loads(line)["global_seq"] for line in events.splitlines()]
        assert globals_ == sorted(globals_)
        memories = (tmp_path / "repo" / "metadata" / "memories.ndjson").read_text("utf-8")
        ids = [json.loads(line)["id"] for line in memories.splitlines()]
        assert ids == sorted(ids)


@pytest.mark.integration
class TestIncremental:
    def test_incremental_append_equals_full_rewrite(
        self, space: Space, seeded: dict[str, MemoryId], tmp_path: Path
    ) -> None:
        root = tmp_path / "repo"
        space.exporter.export(root)
        # New history after the first export.
        version = space.query.get(seeded["fact"]).version
        space.commands.edit_memory(
            seeded["fact"],
            EditMemoryInput(expected_version=version, content="updated content"),
            USER,
        )
        incremental = space.exporter.export(root, incremental=True)
        full = space.exporter.export(tmp_path / "fresh")
        # Content files byte-identical; the manifests differ only in volatile
        # metadata (generated_at/duration), which the merkle root ignores.
        assert _content_files(_tree(root)) == _content_files(_tree(tmp_path / "fresh"))
        assert incremental.manifest.merkle_root == full.manifest.merkle_root

    def test_slug_rename_deletes_the_orphan_file(
        self, space: Space, seeded: dict[str, MemoryId], tmp_path: Path
    ) -> None:
        root = tmp_path / "repo"
        space.exporter.export(root)
        old_slug = space.query.get(seeded["project"]).slug
        version = space.query.get(seeded["project"]).version
        space.commands.edit_memory(
            seeded["project"],
            EditMemoryInput(expected_version=version, slug="engram-renamed"),
            USER,
        )
        report = space.exporter.export(root)
        assert f"memory/projects/{old_slug}.md" in report.deleted
        assert not (root / "memory" / "projects" / f"{old_slug}.md").exists()
        assert (root / "memory" / "projects" / "engram-renamed.md").exists()


@pytest.mark.integration
class TestManifest:
    def test_manifest_counts_and_checksums_are_honest(
        self, space: Space, seeded: dict[str, MemoryId], tmp_path: Path
    ) -> None:
        root = tmp_path / "repo"
        report = space.exporter.export(root)
        manifest = parse_manifest((root / "manifest.json").read_text("utf-8"))
        assert manifest.counts["memories"] == 5
        assert manifest.counts["links"] == 2
        assert manifest.counts["relationship_objects"] == 1
        assert manifest.counts["events"] == manifest.head_global_seq

        on_disk = {path: (root / path).read_bytes() for path in manifest.files}
        assert verify_files(manifest.files, on_disk) == []
        assert manifest.merkle_root == merkle_root(manifest.files)
        assert report.manifest.merkle_root == manifest.merkle_root

    def test_tampering_is_detected(
        self, space: Space, seeded: dict[str, MemoryId], tmp_path: Path
    ) -> None:
        root = tmp_path / "repo"
        space.exporter.export(root)
        manifest = parse_manifest((root / "manifest.json").read_text("utf-8"))
        victim = next(path for path in manifest.files if path.endswith(".md"))
        (root / victim).write_text("tampered", encoding="utf-8")
        on_disk = {path: (root / path).read_bytes() for path in manifest.files}
        assert verify_files(manifest.files, on_disk) == [victim]

    def test_markdown_only_export_skips_ndjson(
        self, space: Space, seeded: dict[str, MemoryId], tmp_path: Path
    ) -> None:
        root = tmp_path / "repo"
        space.exporter.export(root, export_format="markdown")
        assert not (root / "timeline").exists()
        assert (root / "memory" / "facts").exists()

    def test_unknown_format_rejected(self, space: Space, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="unknown export format"):
            space.exporter.export(tmp_path / "repo", export_format="pdf")

    def test_sha256_helper_is_plain_sha256(self) -> None:
        import hashlib

        assert sha256_hex(b"engram") == hashlib.sha256(b"engram").hexdigest()


@pytest.mark.integration
def test_export_only_touches_its_own_lanes(
    space: Space, seeded: dict[str, MemoryId], tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    foreign = root / "NOTES-not-engrams.md"
    foreign.write_text("mine", encoding="utf-8")
    space.exporter.export(root)
    assert foreign.read_text(encoding="utf-8") == "mine"
    assert layout.KIND_DIRS  # the lanes are enumerable, not guessed
