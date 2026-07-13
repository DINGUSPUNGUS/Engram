"""Frontmatter contract: deterministic render, faithful parse, hostile input."""

import pytest
import yaml
from export_harness import Space, seed_rich_space

from engram_core.domain.errors import ValidationError
from engram_export_git.frontmatter import parse_document, render_document


@pytest.mark.integration
class TestRoundTrip:
    def test_render_then_parse_preserves_every_field(self, space: Space) -> None:
        ids = seed_rich_space(space)
        model = space.query.get(ids["fact"])
        document = render_document(model)

        parsed = parse_document(document)
        assert parsed.meta["id"] == str(model.id)
        assert parsed.meta["kind"] == "fact"
        assert parsed.meta["title"] == model.title  # quotes/dashes survive JSON quoting
        assert parsed.meta["confidence"] == model.confidence
        assert parsed.meta["created_by"] == model.created_by
        assert parsed.meta["tags"] == sorted(model.tags)
        assert parsed.meta["links"] == [
            {"relation": "about", "target": str(model.links[0].target_id)}
        ]
        assert parsed.meta["attributes"] == {"statement": "User prefers dark mode"}
        assert parsed.body == model.content.rstrip()
        assert parsed.evidence[0]["type"] == "quote"
        assert parsed.evidence[0]["value"] == "let's always use dark mode"

    def test_render_is_valid_yaml_for_any_reader(self, space: Space) -> None:
        ids = seed_rich_space(space)
        for memory_id in ids.values():
            document = render_document(space.query.get(memory_id))
            raw_meta = document.split("\n---\n", 1)[0].removeprefix("---\n")
            assert isinstance(yaml.safe_load(raw_meta), dict)

    def test_render_is_stable_across_calls(self, space: Space) -> None:
        ids = seed_rich_space(space)
        model = space.query.get(ids["relationship"])
        assert render_document(model) == render_document(model)


@pytest.mark.unit
class TestHostileInput:
    def test_missing_frontmatter_rejected(self) -> None:
        with pytest.raises(ValidationError, match="frontmatter"):
            parse_document("just some text")

    def test_unterminated_frontmatter_rejected(self) -> None:
        with pytest.raises(ValidationError, match="unterminated"):
            parse_document("---\nid: x\n")

    def test_non_mapping_frontmatter_rejected(self) -> None:
        with pytest.raises(ValidationError, match="mapping"):
            parse_document("---\n- a list\n---\nbody")

    def test_unterminated_evidence_block_rejected(self) -> None:
        with pytest.raises(ValidationError, match="evidence"):
            parse_document('---\nid: "x"\n---\nbody\n\n## Evidence\n\n```yaml\n- type: quote\n')

    def test_body_containing_evidence_heading_prose_is_kept(self) -> None:
        text = '---\nid: "x"\n---\nI once wrote ## Evidence inline — not a section.\n'
        parsed = parse_document(text)
        assert "## Evidence" in parsed.body
        assert parsed.evidence == ()
