"""Import contract: exhaustive validation, proposals-only, guarded restore."""

from pathlib import Path

import pytest
from export_harness import Space, build_space, seed_rich_space

from engram_core.domain.errors import ConflictError, ValidationError
from engram_core.domain.events import ProposalOpened
from engram_events import Provenance
from engram_export_git.manifest import parse_manifest

USER = Provenance(actor="user", detail="test-import")

VALID_DOC = """---
id: "0198aaaa-0000-7000-8000-000000000001"
kind: "fact"
schema_version: 1
title: "Imported fact"
slug: "imported-fact"
created_at: "2026-07-01T00:00:00Z"
updated_at: "2026-07-01T00:00:00Z"
created_by: "user"
confidence: 0.8
visibility: "shared"
lifetime: "standard"
tags:
  - "imported"
links:
  - relation: "about"
    target: "0198aaaa-0000-7000-8000-000000000002"
attributes:
  statement: "imported knowledge"
---

The narrative body.

## Evidence

```yaml
- type: "quote"
  value: "someone said so"
```
"""

COMPANION_DOC = """---
id: "0198aaaa-0000-7000-8000-000000000002"
kind: "project"
schema_version: 1
title: "Imported project"
confidence: 0.9
attributes:
  name: "imported"
  status: "active"
---
"""


@pytest.mark.integration
class TestProposalImport:
    def test_valid_import_opens_one_proposal_with_all_drafts(
        self, space: Space, tmp_path: Path
    ) -> None:
        source = tmp_path / "docs"
        source.mkdir()
        (source / "fact.md").write_text(VALID_DOC, encoding="utf-8")
        (source / "project.md").write_text(COMPANION_DOC, encoding="utf-8")

        before = len(space.store.read_all())
        report = space.importer.import_documents(source, USER)
        assert (report.memories, report.links, report.evidence) == (2, 1, 1)

        # Exactly one new event: the ProposalOpened. No memory stream was touched.
        after = space.store.read_all()
        assert len(after) == before + 1
        opened = after[-1].payload
        assert isinstance(opened, ProposalOpened)
        assert len(opened.proposed_events) == 4  # 2 created + 1 link + 1 evidence
        types = sorted(str(d["event_type"]) for d in opened.proposed_events)
        assert types == [
            "MemoryCreated",
            "MemoryCreated",
            "MemoryEvidenceAdded",
            "MemoryLinked",
        ]
        # Nothing appears in projected state until a human merges (M4).
        assert space.query.list_memories(include_archived=True).items == ()

    def test_hand_written_file_without_id_gets_identity_minted(
        self, space: Space, tmp_path: Path
    ) -> None:
        doc = tmp_path / "note.md"
        doc.write_text(
            '---\nkind: "fact"\ntitle: "No id"\nattributes:\n  statement: "x"\n---\nbody\n',
            encoding="utf-8",
        )
        report = space.importer.import_documents(doc, USER)
        assert report.memories == 1

    def test_windows_bom_does_not_hide_the_frontmatter(self, space: Space, tmp_path: Path) -> None:
        doc = tmp_path / "bom.md"
        doc.write_text(
            '---\nkind: "fact"\ntitle: "BOM note"\nattributes:\n  statement: "x"\n---\nbody\n',
            encoding="utf-8-sig",  # what PowerShell 5.1 / Notepad produce
        )
        report = space.importer.import_documents(doc, USER)
        assert report.memories == 1

    def test_malformed_documents_are_all_reported_and_nothing_is_written(
        self, space: Space, tmp_path: Path
    ) -> None:
        source = tmp_path / "docs"
        source.mkdir()
        (source / "bad.md").write_text(
            "---\n"
            'id: "not-a-uuid"\n'
            'kind: "banana"\n'
            'title: ""\n'
            "confidence: 7\n"
            'visibility: "loud"\n'
            "links:\n"
            '  - relation: "hugs"\n'
            '    target: "also-not-a-uuid"\n'
            "evidence: []\n"
            "attributes: {}\n"
            "---\nbody\n",
            encoding="utf-8",
        )
        before = len(space.store.read_all())
        with pytest.raises(ValidationError) as excinfo:
            space.importer.import_documents(source, USER)
        message = str(excinfo.value)
        for fragment in ("not-a-uuid", "unknown kind", "title", "confidence", "visibility", "hugs"):
            assert fragment in message, f"missing {fragment!r} in: {message}"
        assert len(space.store.read_all()) == before  # nothing written

    def test_link_to_unknown_target_is_rejected(self, space: Space, tmp_path: Path) -> None:
        doc = tmp_path / "dangling.md"
        doc.write_text(VALID_DOC, encoding="utf-8")  # companion is absent this time
        with pytest.raises(ValidationError, match="not part of this import"):
            space.importer.import_documents(doc, USER)

    def test_evidence_vocabulary_is_enforced(self, space: Space, tmp_path: Path) -> None:
        doc = tmp_path / "ev.md"
        doc.write_text(
            VALID_DOC.replace('- type: "quote"', '- type: "vibes"').replace(
                'links:\n  - relation: "about"\n    target: "0198aaaa-0000-7000-8000-000000000002"',
                "links: []",
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValidationError, match="unknown evidence type"):
            space.importer.import_documents(doc, USER)


@pytest.mark.integration
class TestRestoreGuards:
    def test_restore_refuses_a_non_empty_space(self, space: Space, tmp_path: Path) -> None:
        seed_rich_space(space)
        repo = tmp_path / "repo"
        space.exporter.export(repo)
        with pytest.raises(ConflictError, match="non-empty"):
            space.importer.restore(repo)

    def test_restore_rejects_a_tampered_event_log(self, space: Space, tmp_path: Path) -> None:
        seed_rich_space(space)
        repo = tmp_path / "repo"
        space.exporter.export(repo)
        events = repo / "timeline" / "events.ndjson"
        events.write_bytes(events.read_bytes() + b'{"forged": true}\n')
        reborn = build_space(tmp_path / "reborn.db")
        with pytest.raises(ValidationError, match="checksum"):
            reborn.importer.restore(repo)

    def test_restore_rejects_broken_stream_ordering(self, space: Space, tmp_path: Path) -> None:
        seed_rich_space(space)
        repo = tmp_path / "repo"
        space.exporter.export(repo)
        events = repo / "timeline" / "events.ndjson"
        lines = events.read_text(encoding="utf-8").splitlines()
        events.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")  # drop event #1
        reborn = build_space(tmp_path / "reborn.db")
        # Bare file (no manifest check) still fails on ordering validation.
        with pytest.raises(ValidationError, match="expected stream_seq"):
            reborn.importer.restore(events)


@pytest.mark.integration
class TestCrossVersion:
    def test_newer_manifest_is_refused_with_upgrade_guidance(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="upgrade engram"):
            parse_manifest('{"manifest_schema_version": 99}')

    def test_newer_memory_record_schema_is_refused(self, space: Space, tmp_path: Path) -> None:
        ndjson_file = tmp_path / "memories.ndjson"
        ndjson_file.write_text(
            '{"record_schema_version": 99, "id": "0198aaaa-0000-7000-8000-000000000009"}\n',
            encoding="utf-8",
        )
        with pytest.raises(ValidationError, match="record schema version"):
            space.importer.import_documents(ndjson_file, USER)

    def test_memories_ndjson_round_trips_through_import(self, space: Space, tmp_path: Path) -> None:
        seed_rich_space(space)
        repo = tmp_path / "repo"
        space.exporter.export(repo)
        fresh = build_space(tmp_path / "fresh.db")
        report = fresh.importer.import_documents(
            repo / "metadata" / "memories.ndjson", USER, title="bulk import"
        )
        assert report.memories == 5
        assert report.links == 2
        assert report.evidence == 1
