"""The two-suite summary: one table per batch of questions, plus the total."""

from eurohistory_rag.eval.report import render_by_suite
from tests.eval.test_metrics import make_record


def test_one_table_per_suite_plus_a_combined_one() -> None:
    records = [
        make_record(question_id="g1", suite="golden"),
        make_record(question_id="e1", suite="extended"),
    ]
    out = render_by_suite(records)
    assert "--- golden (1 questions)" in out
    assert "--- extended (1 questions)" in out
    assert "--- all suites (2 questions)" in out


def test_a_single_suite_gets_no_combined_table() -> None:
    """One batch already is the total, and printing it twice invites reading
    the second copy as a different number."""
    out = render_by_suite([make_record(question_id="g1", suite="golden")])
    assert "--- golden (1 questions)" in out
    assert "all suites" not in out


def test_a_suite_is_scored_only_against_its_own_questions() -> None:
    """The whole point: a batch that misses everything must not be averaged
    away by a batch that hits everything, which is what Phase 14 could not see.
    """
    records = [
        make_record(question_id="g1", suite="golden", expected=["2:0"]),
        make_record(question_id="e1", suite="extended", expected=["999:0"]),
    ]
    blocks = {
        block.split(" ")[0]: block for block in render_by_suite(records).split("--- ")
    }
    assert "100.0%" in blocks["golden"]
    assert "  0.0%" in blocks["extended"]
    assert " 50.0%" in blocks["all"]


def test_the_spend_line_prices_the_run_it_describes() -> None:
    """The cost of a finished run, from its own tokens rather than an estimate.

    Two questions at 2,600 prompt tokens with 1,300 of them cached, plus 100
    completion tokens each -- the line has to name both the dollars and the
    cached share, because a spend figure with no share behind it cannot be
    checked. D-103.
    """
    records = [
        make_record(
            question_id=f"g{n}",
            prompt_tokens=2600,
            cached_tokens=1300,
            completion_tokens=100,
        )
        for n in (1, 2)
    ]

    out = render_by_suite(records)

    assert "cached: 2,600 prompt tokens, 50.0%" in out
    assert "spend: $0.00" in out


def test_a_run_with_no_cached_counts_says_unknown_rather_than_zero() -> None:
    """Every run made before Phase 29 is in this state, and a dollar figure
    there would charge full price for tokens nobody measured."""
    out = render_by_suite([make_record(question_id="g1", prompt_tokens=2600)])

    assert "spend: unknown" in out
