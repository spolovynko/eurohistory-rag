"""Reading a recorded trace back, and what the attribution must never claim."""

from eurohistory_rag.core.trace import Span
from eurohistory_rag.eval.record import CitationRef, EvalRecord, Retrieved
from eurohistory_rag.eval.timeline import (
    render_one,
    render_run,
    stage_shares,
    unattributed_ms,
)


def record(
    question_id: str = "q1",
    total_ms: float = 1000.0,
    spans: list[Span] | None = None,
) -> EvalRecord:
    """A record carrying nothing but the fields a timeline reads."""
    return EvalRecord(
        question_id=question_id,
        question="why?",
        kind="easy",
        expected_doc_ids=[],
        retrieved=[
            Retrieved(
                rank=1, chunk_id="c0", doc_id="d0", page_id=1, source="s", score=0.5
            )
        ],
        answer="an answer [1]",
        generation_model="fake",
        sources_sent=1,
        markers_found=[1],
        citations=[CitationRef(number=1, doc_id="d0", source="s")],
        search_ms=200.0,
        generate_ms=780.0,
        total_ms=total_ms,
        trace=spans or [],
    )


def test_children_are_not_counted_twice_against_the_wall_clock() -> None:
    """The mistake that makes an attribution add up to more than 100%.

    `embed` and `dense` are already inside `search`. Adding all four would
    claim 400 ms of a 1,000 ms question for 200 ms of work.
    """
    spans = [
        Span(name="search", depth=0, ms=200.0),
        Span(name="embed", depth=1, ms=120.0),
        Span(name="dense", depth=1, ms=80.0),
        Span(name="generate", depth=0, ms=700.0),
    ]
    assert unattributed_ms(record(spans=spans)) == 100.0


def test_a_run_with_no_traces_says_so_rather_than_reporting_zeroes() -> None:
    """26 runs on disk predate this field, and 0.0 ms is a lie about them."""
    assert "predates Phase 28" in render_run([record()])


def test_a_stage_is_scored_only_over_the_questions_that_ran_it() -> None:
    """`rewrite` runs on 14 of 106. Averaging it over 106 divides it by seven."""
    with_rewrite = record("q1", 1000.0, [Span(name="rewrite", depth=0, ms=400.0)])
    without = record("q2", 1000.0, [Span(name="generate", depth=0, ms=800.0)])

    shares = {s.name: s for s in stage_shares([with_rewrite, without])}
    assert shares["rewrite"].questions == 1
    assert shares["rewrite"].median_share == 0.4


def test_one_question_prints_its_stages_indented_under_their_parent() -> None:
    spans = [
        Span(name="search", depth=0, ms=200.0, note="5 chunks"),
        Span(name="embed", depth=1, ms=120.0, note="1536 dims"),
    ]
    rendered = render_one(record(spans=spans))

    assert "search" in rendered
    assert "  embed" in rendered
    assert "unattributed" in rendered


def test_a_question_that_took_no_time_does_not_divide_by_zero() -> None:
    """A recorded failure can carry a zero clock, and a report must still print."""
    assert "unattributed" in render_one(record(total_ms=0.0))
