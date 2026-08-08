"""Which of the three rungs a chunk's period comes from, and what it says."""

from eurohistory_rag.pipeline.gold.dates import Span, chunk_span, years_in


def test_a_heading_range_wins_over_everything_below_it() -> None:
    """The editor declared the scope. Nothing in the body outranks that."""
    span = chunk_span(
        heading="Containment, Truman Doctrine, Korean War (1947–1953)",
        title="Cold War",
        text="In February 1946, George F. Kennan's Long Telegram...",
    )
    assert span == Span(1947, 1953, "heading")


def test_a_bare_year_heading_becomes_a_one_year_span() -> None:
    assert chunk_span("1916", "Western Front (World War I)", "Falkenhayn believed") == (
        Span(1916, 1916, "heading")
    )


def test_the_title_is_used_when_the_heading_has_no_year() -> None:
    span = chunk_span(
        "Negotiations", "2007 enlargement of the European Union", "Romania"
    )
    assert span == Span(2007, 2007, "title")


def test_the_body_is_the_fallback_when_neither_names_a_year() -> None:
    span = chunk_span("Fall", "Berlin Wall", "On 9 November 1989 the crossings opened.")
    assert span == Span(1989, 1989, "text")


def test_a_chunk_with_no_year_anywhere_gets_no_span() -> None:
    """26.7% of the corpus. They must be filtered out of nothing."""
    span = chunk_span("Structure", "Berlin Wall", "The wall had a concrete face.")
    assert span is None


def test_the_body_span_is_the_plain_minimum_and_maximum() -> None:
    """No trimming, on purpose: a stray year widens, and wider is the safe way.

    D-096 argues this rather than assuming it, so the behaviour is pinned here.
    """
    assert years_in("From 1918 to 1923, and again briefly in 1889.") == (1889, 1923)


def test_numbers_outside_the_year_window_are_not_years() -> None:
    assert years_in("2,400 tons carried by 1,799 aircraft") is None
