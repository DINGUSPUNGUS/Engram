"""The query language parser (ADR-0016): one grammar, deterministically parsed."""

from datetime import UTC, datetime, timedelta

import pytest

from engram_core.application.dto import ConfidenceFilter, MemoryQuerySpec
from engram_core.application.queries.query_language import parse_query
from engram_core.domain.errors import ValidationError
from engram_core.domain.kinds import build_kind_registry
from engram_core.domain.values import MemoryKind, Visibility

NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=UTC)
KINDS = build_kind_registry()


def parse(query: str) -> MemoryQuerySpec:
    return parse_query(query, now=NOW, kinds=KINDS)


@pytest.mark.unit
class TestFreeText:
    def test_bare_words_become_quoted_fts_terms(self) -> None:
        assert parse("dark mode").text == '"dark" "mode"'

    def test_quoted_phrase_survives_as_one_term(self) -> None:
        assert parse('"dark mode"').text == '"dark mode"'

    def test_fts_syntax_cannot_be_injected(self) -> None:
        # Every term is quoted, so OR/NEAR/prefix syntax stays literal text.
        assert parse("star* OR moon").text == '"star*" "OR" "moon"'

    def test_url_is_text_not_attribute(self) -> None:
        spec = parse("https://example.com")
        assert spec.attributes == ()
        assert spec.text == '"https://example.com"'


@pytest.mark.unit
class TestOperators:
    def test_kind(self) -> None:
        assert parse("kind:project").kind is MemoryKind.PROJECT

    def test_unknown_kind_rejected(self) -> None:
        with pytest.raises(ValidationError, match="unknown kind"):
            parse("kind:banana")

    def test_tags_accumulate_and_normalize(self) -> None:
        assert parse("tag:OSS tag:infra").tags == ("oss", "infra")

    def test_slug_and_visibility(self) -> None:
        spec = parse("slug:engram-a1b2 visibility:private")
        assert spec.slug == "engram-a1b2"
        assert spec.visibility is Visibility.PRIVATE

    def test_is_flags(self) -> None:
        spec = parse("is:archived is:pinned is:stale")
        assert (spec.archived, spec.pinned, spec.stale) == (True, True, True)
        with pytest.raises(ValidationError, match="is: expects"):
            parse("is:awesome")

    def test_has(self) -> None:
        assert parse("has:evidence has:links").has == frozenset({"evidence", "links"})
        with pytest.raises(ValidationError, match="has: expects"):
            parse("has:vibes")

    def test_attribute_fallthrough_uses_schema_vocabulary(self) -> None:
        spec = parse("status:active name:engram")
        assert spec.attributes == (("status", "active"), ("name", "engram"))

    def test_non_schema_key_is_free_text(self) -> None:
        spec = parse("frobnicate:yes")
        assert spec.attributes == ()
        assert spec.text == '"frobnicate:yes"'

    def test_linked_strips_kind_prefix(self) -> None:
        assert parse("linked:person/jude-a1b2").linked == "jude-a1b2"
        assert parse("linked:jude-a1b2").linked == "jude-a1b2"

    def test_duplicate_single_valued_operator_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate operator"):
            parse("kind:fact kind:project")


@pytest.mark.unit
class TestConfidence:
    def test_comparisons(self) -> None:
        assert parse("confidence>0.8").confidence == ConfidenceFilter(op=">", value=0.8)
        assert parse("confidence<=0.5").confidence == ConfidenceFilter(op="<=", value=0.5)

    def test_needs_a_number(self) -> None:
        with pytest.raises(ValidationError, match="needs a number"):
            parse("confidence>high")

    def test_colon_form_gets_a_teaching_error(self) -> None:
        with pytest.raises(ValidationError, match="comparison"):
            parse("confidence:0.8")

    def test_comparison_on_other_fields_rejected(self) -> None:
        with pytest.raises(ValidationError, match="comparison only applies"):
            parse("version>3")


@pytest.mark.unit
class TestDates:
    def test_relative_days(self) -> None:
        assert parse("updated:last30days").updated_after == NOW - timedelta(days=30)

    def test_today_is_midnight(self) -> None:
        assert parse("created:today").created_after == NOW.replace(hour=0, minute=0)

    def test_absolute_date(self) -> None:
        assert parse("updated:2026-07-01").updated_after == datetime(2026, 7, 1, tzinfo=UTC)

    def test_bad_date_rejected(self) -> None:
        with pytest.raises(ValidationError, match="bad date"):
            parse("updated:whenever")


@pytest.mark.unit
class TestWholeQueries:
    def test_the_adr_example(self) -> None:
        spec = parse('kind:project status:active tag:oss confidence>0.8 "dark mode"')
        assert spec.kind is MemoryKind.PROJECT
        assert spec.attributes == (("status", "active"),)
        assert spec.tags == ("oss",)
        assert spec.confidence == ConfidenceFilter(op=">", value=0.8)
        assert spec.text == '"dark mode"'

    def test_empty_query_rejected(self) -> None:
        with pytest.raises(ValidationError, match="empty query"):
            parse("   ")

    def test_unbalanced_quotes_rejected(self) -> None:
        with pytest.raises(ValidationError, match="unbalanced quotes"):
            parse('kind:fact "dark')
