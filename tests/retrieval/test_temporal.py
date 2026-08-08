"""What the query parser reads out of a question, and what it refuses to."""

import pytest

from eurohistory_rag.retrieval.temporal import Period, parse_period


@pytest.mark.parametrize(
    ("question", "start", "end"),
    [
        ("What happened between 1947 and 1953?", 1947, 1953),
        ("How did it change from 1973 to 1993?", 1973, 1993),
        ("Renewal of tensions 1979-1985", 1979, 1985),
        ("Renewal of tensions 1979–1985", 1979, 1985),
        ("What happened in 1916?", 1916, 1916),
        ("the middle of 1940 and early 1941", 1940, 1941),
        ("What happened during the 1970s?", 1970, 1979),
        ("What happened in the early 1980s?", 1980, 1983),
        ("What happened in the late 1930s?", 1936, 1939),
        ("What happened in the mid-1960s?", 1964, 1966),
    ],
)
def test_absolute_periods_are_read(question: str, start: int, end: int) -> None:
    assert parse_period(question) == Period(start, end)


@pytest.mark.parametrize(
    ("question", "start", "end"),
    [
        ("What did the First World War do to the empires?", 1914, 1918),
        ("How was the Second World War fought at sea?", 1939, 1945),
        ("What were the interwar years like in Germany?", 1918, 1939),
        ("How did the Cold War divide Europe?", 1947, 1991),
        ("What marked the early Cold War?", 1947, 1962),
    ],
)
def test_named_eras_are_read(question: str, start: int, end: int) -> None:
    assert parse_period(question) == Period(start, end)


def test_the_longest_era_name_wins() -> None:
    """The longest name wins, so "cold war" cannot swallow "early cold war"."""
    assert parse_period("the early Cold War") == Period(1947, 1962)


@pytest.mark.parametrize(
    "question",
    [
        "What happened after the war?",
        "What was Germany made to pay after 1918?",
        "What did Eisenhower do between the end of the Second World War and 1953?",
        "Why did German money lose its value just after the First World War?",
        "Why did Nokia lose its lead after 2007?",
        "What did the Treaty of Brest-Litovsk take from Russia?",
        "How does a plant turn sunlight into sugar?",
    ],
)
def test_ambiguous_and_undated_questions_resolve_to_nothing(question: str) -> None:
    """The refusal is the feature.

    A date next to "after" or "the end of" is a reference point, not a period:
    how far past it the question reaches cannot be read off the words, and this
    corpus contains two world wars and a cold one. Guessing is worse than
    declining, because the temporal arm would then push retrieval at exactly the
    wrong sections. See D-096.
    """
    assert parse_period(question) is None


def test_explicit_ranges_survive_a_directional_word() -> None:
    """A stated range carries its own width, whatever else the sentence does."""
    assert parse_period("after the war, between 1947 and 1953") == Period(1947, 1953)


def test_absolute_years_beat_a_named_era_in_the_same_question() -> None:
    assert parse_period("the 1919 treaty ending the First World War") == Period(
        1919, 1919
    )


def test_a_period_cannot_run_backwards() -> None:
    with pytest.raises(ValueError, match="backwards"):
        Period(1953, 1947)


def test_four_digit_numbers_outside_the_year_range_are_not_years() -> None:
    """A casualty figure is not a date. 1799 and 2030 are outside the window."""
    assert parse_period("How many of the 1799 men survived?") is None


# --- how well a chunk's span agrees with the question's (D-096 addendum) -----


def test_an_exact_match_agrees_completely() -> None:
    assert Period(1979, 1985).agreement(1979, 1985) == 1.0


def test_a_one_year_touch_scores_far_below_an_exact_match() -> None:
    """The defect the addendum exists for, pinned as a number.

    `Cold War (1985-1991)` touches a question about 1979-1985 by the year 1985
    alone. Under a yes/no filter it ranked first and displaced the section
    covering the period exactly.
    """
    period = Period(1979, 1985)
    assert period.agreement(1985, 1991) == pytest.approx(1 / 13)
    assert period.agreement(1985, 1991) < period.agreement(1979, 1985)


def test_a_span_wide_enough_to_cover_everything_scores_almost_nothing() -> None:
    """Why coverage alone was not enough: vagueness would have won every arm."""
    assert Period(1948, 1949).agreement(1800, 2024) == pytest.approx(2 / 225)


def test_a_span_that_does_not_touch_scores_zero() -> None:
    assert Period(1948, 1949).agreement(1961, 1989) == 0.0


def test_an_undated_chunk_scores_zero_rather_than_raising() -> None:
    """28% of the corpus. Scoring last is fine; crashing is not."""
    assert Period(1948, 1949).agreement(None, None) == 0.0


def test_every_decade_named_is_covered_not_just_the_first() -> None:
    """ "the 1950s and 1960s" is twenty years, and reading ten of them cost a
    real question its answer past rank 20. See the D-096 third addendum."""
    assert parse_period("cars and washing machines in the 1950s and 1960s") == Period(
        1950, 1969
    )


def test_qualifiers_apply_to_the_decade_they_sit_beside() -> None:
    assert parse_period("from the late 1930s to the early 1950s") == Period(1936, 1953)
