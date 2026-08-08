"""The maths, checked against hand-computed answers."""

from eurohistory_rag.eval.metrics import (
    coverage_at,
    distinct_articles,
    distinct_documents,
    first_token_ms,
    hit_at,
    invalid_markers,
    reciprocal_rank,
    refused,
    summarise,
    summarise_by_kind,
)
from eurohistory_rag.eval.record import CitationRef, EvalRecord, Retrieved


def make_record(
    *,
    question_id: str = "q",
    kind: str = "easy",
    suite: str = "golden",
    expected: list[str] | None = None,
    doc_ids: list[str] | None = None,
    page_ids: list[int] | None = None,
    answer: str = "Because of the treaty [1].",
    markers: list[int] | None = None,
    cited: bool = True,
    sources_sent: int = 5,
    total_ms: float = 100.0,
    ttft_ms: float | None = None,
) -> EvalRecord:
    """An EvalRecord with only the fields a metric reads set meaningfully."""
    docs = doc_ids if doc_ids is not None else ["1:0", "2:0", "3:0"]
    pages = page_ids if page_ids is not None else [int(d.split(":")[0]) for d in docs]
    return EvalRecord(
        question_id=question_id,
        question="why?",
        kind=kind,
        suite=suite,
        expected_doc_ids=expected if expected is not None else ["2:0"],
        retrieved=[
            Retrieved(
                rank=i,
                chunk_id=f"{doc}:{i}",
                doc_id=doc,
                page_id=page,
                source=f"Article {doc}",
                score=1.0 - i / 100,
            )
            for i, (doc, page) in enumerate(zip(docs, pages, strict=True), start=1)
        ],
        answer=answer,
        generation_model="fake",
        sources_sent=sources_sent,
        markers_found=markers if markers is not None else [1],
        citations=(
            [CitationRef(number=1, doc_id=docs[0], source="Article")] if cited else []
        ),
        search_ms=10.0,
        generate_ms=90.0,
        total_ms=total_ms,
        first_token_ms=ttft_ms,
    )


def test_a_run_made_before_streaming_had_its_first_token_at_the_end() -> None:
    """The fallback that makes every run already on disk a valid "before"."""
    assert first_token_ms(make_record(total_ms=4000.0)) == 4000.0


def test_a_streamed_record_reports_the_moment_it_recorded() -> None:
    assert first_token_ms(make_record(total_ms=4000.0, ttft_ms=900.0)) == 900.0


def test_the_summary_reports_a_median_first_token_across_both_kinds() -> None:
    """A mixed set: two streamed, one not, so the fallback has to be in the sort."""
    records = [
        make_record(total_ms=4000.0),
        make_record(total_ms=4000.0, ttft_ms=800.0),
        make_record(total_ms=4000.0, ttft_ms=900.0),
    ]
    assert summarise(records).p50_first_token_ms == 900.0


def test_hit_at_respects_the_depth() -> None:
    record = make_record(expected=["3:0"])
    assert not hit_at(record, 2)
    assert hit_at(record, 3)


def test_coverage_sees_the_one_sided_answer_that_recall_calls_a_hit() -> None:
    """A comparison question returning only one side: a hit, a third covered."""
    record = make_record(expected=["1:0", "8:0", "9:0"])
    assert hit_at(record, 5)
    assert coverage_at(record, 5) == 1 / 3


def test_reciprocal_rank_is_one_over_the_first_hit() -> None:
    assert reciprocal_rank(make_record(expected=["1:0"])) == 1.0
    assert reciprocal_rank(make_record(expected=["3:0"])) == 1 / 3


def test_reciprocal_rank_is_zero_on_a_miss() -> None:
    assert reciprocal_rank(make_record(expected=["99:9"])) == 0.0


def test_refusal_matches_the_phrase_the_prompt_actually_asks_for() -> None:
    """Pinned to system_prompt.md. The first baseline read 0% because it was guessed."""
    assert refused(make_record(answer="Not in the sources. The corpus covers..."))
    assert not refused(make_record(answer="The wall went up in 1961."))


def test_invalid_markers_are_those_past_the_sources_sent() -> None:
    record = make_record(markers=[1, 3, 7], sources_sent=5)
    assert invalid_markers(record) == [7]


def test_distinct_counts_separate_sections_from_articles() -> None:
    """Two sections of one article: two documents, one article."""
    record = make_record(doc_ids=["7:0", "7:1", "9:0"], page_ids=[7, 7, 9])
    assert distinct_documents(record, 5) == 3
    assert distinct_articles(record, 5) == 2


def test_summary_leaves_recall_unset_when_nothing_has_an_answer_key() -> None:
    """The six unanswerable questions must not be scored as zero recall."""
    summary = summarise([make_record(kind="unanswerable", expected=[])])
    assert summary.recall_at_5 is None
    assert summary.mrr is None


def test_summary_counts_a_missing_citation_only_when_it_matters() -> None:
    """A refusal cites nothing and that is correct, so it is not counted."""
    summary = summarise(
        [
            make_record(
                question_id="a", answer="Not in the sources.", markers=[], cited=False
            ),
            make_record(
                question_id="b", answer="A bare claim.", markers=[], cited=False
            ),
        ]
    )
    assert summary.answers_with_no_citation == 1


def test_summarise_by_kind_adds_a_total_row_last() -> None:
    records = [make_record(kind="easy"), make_record(kind="multi")]
    summaries = summarise_by_kind(records)
    assert [s.kind for s in summaries] == ["easy", "multi", "all"]
    assert summaries[-1].questions == 2
