"""Splitting an article into the rows Silver stores."""

from eurohistory_rag.pipeline.silver.sections import (
    MIN_SECTION_CHARS,
    split_sections,
)

LONG = "Prose about the subject, long enough to clear the minimum. " * 6


def article(*sections: tuple[str, str], lead: str = LONG) -> str:
    """A wikitext article: a lead, then `== heading ==` blocks."""
    parts = [lead]
    parts += [f"== {heading} ==\n{body}" for heading, body in sections]
    return "\n\n".join(parts)


# --- what becomes a row ----------------------------------------------------


def test_the_lead_becomes_a_row_with_an_empty_heading() -> None:
    """No flag needed: the empty heading is what identifies the lead."""
    sections = split_sections(article(("Background", LONG)))

    assert sections[0].heading == ""
    assert sections[0].position == 0


def test_each_level_two_heading_starts_a_new_row() -> None:
    sections = split_sections(article(("Background", LONG), ("Reactions", LONG)))

    assert [s.heading for s in sections] == ["", "Background", "Reactions"]


def test_the_heading_is_not_repeated_in_the_body() -> None:
    """It is a column, so it does not also belong in the text."""
    sections = split_sections(article(("Background", LONG)))

    assert not sections[1].text.startswith("Background")


def test_a_level_three_heading_stays_inside_its_parent() -> None:
    """Splitting deeper is Phase 4's job; here it keeps the row count sane."""
    wikitext = article(("Background", f"=== Origins ===\n{LONG}"))
    sections = split_sections(wikitext)

    assert len(sections) == 2
    assert "Origins" in sections[1].text


def test_positions_are_contiguous_after_filtering() -> None:
    """Position is the order among survivors, not the order in the article."""
    wikitext = article(("References", LONG), ("Reactions", LONG))
    sections = split_sections(wikitext)

    assert [s.position for s in sections] == [0, 1]


def test_the_text_is_cleaned() -> None:
    wikitext = article(("Background", f"The [[Weimar Republic|republic]].{LONG}"))
    sections = split_sections(wikitext)

    assert "[[" not in sections[1].text
    assert "the republic" in sections[1].text.lower()


def test_a_section_carries_its_own_link_targets() -> None:
    """Section-level, not article-level: they describe this passage."""
    wikitext = article(("Background", f"[[Berlin]] {LONG}"), lead=f"[[Rome]] {LONG}")
    sections = split_sections(wikitext)

    assert sections[0].link_targets == ("Rome",)
    assert sections[1].link_targets == ("Berlin",)


# --- what does not become a row --------------------------------------------


def test_an_apparatus_section_is_dropped_by_name() -> None:
    sections = split_sections(article(("References", LONG)))

    assert [s.heading for s in sections] == [""]


def test_a_heading_variant_is_dropped_too() -> None:
    """Matching is exact, so "Notes and references" needs its own entry."""
    sections = split_sections(article(("Notes and references", LONG)))

    assert [s.heading for s in sections] == [""]


def test_the_heading_match_ignores_case() -> None:
    sections = split_sections(article(("EXTERNAL LINKS", LONG)))

    assert [s.heading for s in sections] == [""]


def test_a_section_under_the_minimum_is_dropped() -> None:
    """Under 200 chars is usually the leftovers of a table that was deleted."""
    sections = split_sections(article(("Sister cities", "Kansas City has 15:")))

    assert [s.heading for s in sections] == [""]


def test_the_minimum_is_measured_after_cleaning() -> None:
    """Markup makes a section look long; only the prose counts."""
    short_prose = "Short." + "{{cite book|title=A}}" * 40
    sections = split_sections(article(("Background", short_prose)))

    assert [s.heading for s in sections] == [""]


def test_the_minimum_is_configurable() -> None:
    sections = split_sections(article(("Notes on scope", "Short.")), min_chars=1)

    assert [s.heading for s in sections] == ["", "Notes on scope"]


def test_the_default_minimum_is_the_declared_constant() -> None:
    assert MIN_SECTION_CHARS == 200


def test_an_article_of_only_apparatus_produces_nothing() -> None:
    assert split_sections("== References ==\nSee below.") == []


def test_an_empty_article_produces_nothing() -> None:
    assert split_sections("") == []
