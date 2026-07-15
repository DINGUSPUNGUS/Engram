"""The M4 pipeline end to end: import → proposal → review → merge → undo,
with conflict detection against stream history and replay determinism throughout.
"""

from pathlib import Path

import pytest
from export_harness import USER, Space, seed_rich_space

from engram_core.application.dto import EditMemoryInput, MemoryReadModel
from engram_core.application.queries.proposal_queries import ProposalQueryService
from engram_core.domain.errors import ConflictError, StaleVersionError
from engram_core.domain.values import MemoryId, MemoryKind, ProposalId


def _proposal_queries(space: Space) -> ProposalQueryService:
    from engram_storage_sqlite.repositories import SqliteProposalRepository

    return ProposalQueryService(SqliteProposalRepository(space.store), space.query)


def _view(model: MemoryReadModel) -> tuple[object, ...]:
    """Content equality. ``version`` is deliberately absent: undo *appends*
    compensating events (history grows), it never rewinds the counter."""
    return (
        str(model.id),
        model.title,
        model.content,
        tuple(sorted(model.attributes.items())),
        model.tags,
        tuple(sorted((link.relation, str(link.target_id)) for link in model.links)),
        tuple((e.evidence_type, e.value, e.note) for e in model.evidence),
        model.visibility,
        model.lifetime_policy,
        model.archived,
    )


def _snapshot(space: Space) -> list[tuple[object, ...]]:
    return [_view(m) for m in space.query.list_memories(include_archived=True, limit=200).items]


def _export_edit_import(space: Space, tmp_path: Path, edits: dict[str, str]) -> ProposalId:
    """Export, apply literal text replacements to the fact document, import."""
    repo = tmp_path / "repo"
    space.exporter.export(repo)
    fact_file = next((repo / "memory" / "facts").glob("user-prefers*.md"))
    text = fact_file.read_text(encoding="utf-8")
    for old, new in edits.items():
        assert old in text, f"edit anchor missing: {old!r}"
        text = text.replace(old, new)
    fact_file.write_text(text, encoding="utf-8")
    report = space.importer.import_documents(repo / "memory", USER, title="external edits")
    assert report.proposal_id is not None
    return report.proposal_id


@pytest.mark.integration
class TestReconciler:
    def test_external_edit_produces_edit_drafts_never_a_duplicate(
        self, space: Space, tmp_path: Path
    ) -> None:
        ids = seed_rich_space(space)
        before_count = len(_snapshot(space))
        proposal_id = _export_edit_import(
            space,
            tmp_path,
            {
                'title: "User prefers \\"dark\\" mode — always"': 'title: "User prefers OLED dark"',
                '  - "ui"': '  - "ui"\n  - "displays"',
            },
        )
        detail = _proposal_queries(space).get_proposal(proposal_id)
        ops = sorted(str(draft["op"]) for draft in detail.drafts)
        assert "create_memory" not in ops  # THE requirement: no duplicates
        assert ops == ["edit_memory", "tag_memory"]

        space.proposals.approve_proposal(proposal_id, "lgtm", USER)
        space.proposals.merge_proposal(proposal_id, USER)

        after = space.query.get(ids["fact"])
        assert after.title == "User prefers OLED dark"
        assert "displays" in after.tags
        assert len(_snapshot(space)) == before_count  # still no duplicate

    def test_unchanged_documents_open_no_proposal(self, space: Space, tmp_path: Path) -> None:
        seed_rich_space(space)
        repo = tmp_path / "repo"
        space.exporter.export(repo)
        report = space.importer.import_documents(repo / "memory", USER)
        assert report.proposal_id is None
        assert report.unchanged == 5

    def test_attribute_link_and_evidence_diffs_reconcile(
        self, space: Space, tmp_path: Path
    ) -> None:
        ids = seed_rich_space(space)
        repo = tmp_path / "repo"
        space.exporter.export(repo)
        project_file = next((repo / "memory" / "projects").glob("*.md"))
        text = project_file.read_text(encoding="utf-8")
        text = text.replace('status: "active"', 'status: "paused"')
        project_file.write_text(text, encoding="utf-8")

        report = space.importer.import_documents(repo / "memory", USER)
        assert report.proposal_id is not None
        assert (report.edited, report.created) == (1, 0)
        space.proposals.approve_proposal(report.proposal_id, None, USER)
        space.proposals.merge_proposal(report.proposal_id, USER)
        assert space.query.get(ids["project"]).attributes["status"] == "paused"

    def test_document_for_deleted_memory_is_rejected(self, space: Space, tmp_path: Path) -> None:
        ids = seed_rich_space(space)
        repo = tmp_path / "repo"
        space.exporter.export(repo)
        space.commands.delete_memory(ids["archived"], "gone", USER)
        with pytest.raises(Exception, match="was deleted"):
            space.importer.import_documents(repo / "memory", USER)


@pytest.mark.integration
class TestMergeGuards:
    def test_merge_requires_approval_and_reject_is_final(
        self, space: Space, tmp_path: Path
    ) -> None:
        seed_rich_space(space)
        proposal_id = _export_edit_import(
            space, tmp_path, {'title: "User prefers \\"dark\\" mode — always"': 'title: "x"'}
        )
        with pytest.raises(ConflictError, match="only approved"):
            space.proposals.merge_proposal(proposal_id, USER)
        space.proposals.reject_proposal(proposal_id, "not convinced", USER)
        with pytest.raises(ConflictError, match="already rejected"):
            space.proposals.approve_proposal(proposal_id, None, USER)

    def test_stale_base_version_conflicts_and_nothing_is_appended(
        self, space: Space, tmp_path: Path
    ) -> None:
        ids = seed_rich_space(space)
        proposal_id = _export_edit_import(
            space, tmp_path, {'title: "User prefers \\"dark\\" mode — always"': 'title: "x"'}
        )
        # The target moves AFTER the proposal was opened.
        version = space.query.get(ids["fact"]).version
        space.commands.edit_memory(
            ids["fact"], EditMemoryInput(expected_version=version, title="moved on"), USER
        )
        space.proposals.approve_proposal(proposal_id, None, USER)
        log_before = len(space.store.read_all())
        with pytest.raises(StaleVersionError, match="opened against version"):
            space.proposals.merge_proposal(proposal_id, USER)
        assert len(space.store.read_all()) == log_before  # atomic: nothing landed
        assert space.query.get(ids["fact"]).title == "moved on"


@pytest.mark.integration
class TestUndo:
    def test_undo_restores_pre_merge_state_and_is_event_sourced(
        self, space: Space, tmp_path: Path
    ) -> None:
        ids = seed_rich_space(space)
        before = _snapshot(space)
        log_before = len(space.store.read_all())

        proposal_id = _export_edit_import(
            space,
            tmp_path,
            {
                'title: "User prefers \\"dark\\" mode — always"': 'title: "regrettable edit"',
                '  - "ui"': '  - "ui"\n  - "oops"',
            },
        )
        space.proposals.approve_proposal(proposal_id, None, USER)
        space.proposals.merge_proposal(proposal_id, USER)
        assert space.query.get(ids["fact"]).title == "regrettable edit"

        space.proposals.undo_proposal(proposal_id, "mistake", USER)

        # State is back — but history GREW (append-only): nothing was erased.
        assert _snapshot(space) == before
        assert len(space.store.read_all()) > log_before
        detail = _proposal_queries(space).get_proposal(proposal_id)
        assert detail.status == "undone"
        with pytest.raises(ConflictError, match="only merged"):
            space.proposals.undo_proposal(proposal_id, None, USER)

    def test_undo_of_a_created_memory_tombstones_it(self, space: Space, tmp_path: Path) -> None:
        seed_rich_space(space)
        doc = tmp_path / "new.md"
        doc.write_text(
            '---\nkind: "fact"\ntitle: "Regret"\nattributes:\n  statement: "r"\n---\nbody\n',
            encoding="utf-8",
        )
        report = space.importer.import_documents(doc, USER)
        assert report.proposal_id is not None
        space.proposals.approve_proposal(report.proposal_id, None, USER)
        space.proposals.merge_proposal(report.proposal_id, USER)
        (created_id,) = [
            e.stream_id
            for e in space.store.read_all()
            if e.event_type == "MemoryCreated" and "Regret" in str(e.payload)
        ]
        assert space.query.get(MemoryId(created_id)).title == "Regret"

        space.proposals.undo_proposal(report.proposal_id, None, USER)
        from engram_core.domain.errors import NotFoundError

        with pytest.raises(NotFoundError):
            space.query.get(MemoryId(created_id))

    def test_undo_refuses_when_the_stream_moved_after_merge(
        self, space: Space, tmp_path: Path
    ) -> None:
        ids = seed_rich_space(space)
        proposal_id = _export_edit_import(
            space, tmp_path, {'title: "User prefers \\"dark\\" mode — always"': 'title: "x"'}
        )
        space.proposals.approve_proposal(proposal_id, None, USER)
        space.proposals.merge_proposal(proposal_id, USER)
        version = space.query.get(ids["fact"]).version
        space.commands.edit_memory(
            ids["fact"], EditMemoryInput(expected_version=version, title="later work"), USER
        )
        with pytest.raises(ConflictError, match="changed after the merge"):
            space.proposals.undo_proposal(proposal_id, None, USER)
        assert space.query.get(ids["fact"]).title == "later work"  # untouched

    def test_undo_retracts_evidence_and_replay_stays_deterministic(
        self, space: Space, tmp_path: Path
    ) -> None:
        ids = seed_rich_space(space)
        repo = tmp_path / "repo"
        space.exporter.export(repo)
        fact_file = next((repo / "memory" / "facts").glob("user-prefers*.md"))
        text = fact_file.read_text(encoding="utf-8")
        text = text.replace(
            '- type: "quote"',
            '- type: "uri"\n  value: "https://example.com/proof"\n- type: "quote"',
        )
        fact_file.write_text(text, encoding="utf-8")
        report = space.importer.import_documents(repo / "memory", USER)
        assert report.proposal_id is not None and report.evidence == 1
        space.proposals.approve_proposal(report.proposal_id, None, USER)
        space.proposals.merge_proposal(report.proposal_id, USER)
        assert len(space.query.get(ids["fact"]).evidence) == 2

        space.proposals.undo_proposal(report.proposal_id, None, USER)
        assert len(space.query.get(ids["fact"]).evidence) == 1

        # THE invariant, extended through the whole M4 lifecycle.
        before = _snapshot(space)
        proposals_before = [
            (str(p.id), p.status, p.draft_count)
            for p in _proposal_queries(space).list_proposals(limit=100).items
        ]
        space.rebuild()
        assert _snapshot(space) == before
        assert [
            (str(p.id), p.status, p.draft_count)
            for p in _proposal_queries(space).list_proposals(limit=100).items
        ] == proposals_before


@pytest.mark.integration
def test_merge_creates_memory_with_links_and_evidence_atomically(
    space: Space, tmp_path: Path
) -> None:
    seed_rich_space(space)
    project_id = next(
        m.id for m in space.query.list_memories(kind=MemoryKind.PROJECT, limit=10).items
    )
    doc = tmp_path / "new.md"
    doc.write_text(
        "---\n"
        'kind: "fact"\n'
        'title: "Brand new"\n'
        "links:\n"
        '  - relation: "about"\n'
        f'    target: "{project_id}"\n'
        "attributes:\n"
        '  statement: "brand new"\n'
        "---\n"
        "body\n\n"
        "## Evidence\n\n"
        "```yaml\n"
        '- type: "quote"\n'
        '  value: "heard it"\n'
        "```\n",
        encoding="utf-8",
    )
    report = space.importer.import_documents(doc, USER)
    assert report.proposal_id is not None
    assert (report.created, report.links, report.evidence) == (1, 1, 1)
    space.proposals.approve_proposal(report.proposal_id, None, USER)
    appended = space.proposals.merge_proposal(report.proposal_id, USER)
    assert len(appended) == 3  # created + linked + evidence, one atomic batch

    created = next(
        m
        for m in space.query.list_memories(kind=MemoryKind.FACT, limit=50).items
        if m.title == "Brand new"
    )
    assert [(link.relation, str(link.target_id)) for link in created.links] == [
        ("about", str(project_id))
    ]
    assert created.evidence[0].value == "heard it"
