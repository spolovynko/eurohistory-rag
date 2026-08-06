"""The sweep harness: the fusion maths, the control check, and the ordering."""

from eurohistory_rag.eval.metrics import summarise
from eurohistory_rag.eval.questions import Question
from eurohistory_rag.eval.sweep import (
    Config,
    Pool,
    as_record,
    control_matches,
    rank_for,
    render,
    run_config,
    union,
    weighted_fuse,
)
from eurohistory_rag.retrieval.search import SearchResult


def result(
    chunk_id: str, score: float = 0.5, doc_id: str | None = None
) -> SearchResult:
    """One search result, with only the fields the sweep reads set."""
    return SearchResult(
        chunk_id=chunk_id,
        doc_id=doc_id or chunk_id.rsplit(":", 1)[0],
        page_id=int(chunk_id.split(":")[0]),
        title=f"Article {chunk_id}",
        heading="",
        text=f"text of {chunk_id}",
        score=score,
        revision_id=1,
    )


DENSE = [result("1:0:0"), result("2:0:0"), result("3:0:0")]
SPARSE = [result("9:0:0"), result("2:0:0"), result("1:0:0")]


def test_zero_weight_fusion_reproduces_dense_order() -> None:
    """The control property: at weight 0 the keyword list gets no vote.

    Without this the sweep's "dense only" row and its "fuse w=0.1" row could
    differ for reasons that have nothing to do with BM25.
    """
    fused = weighted_fuse(DENSE, SPARSE, rrf_k=60, sparse_weight=0.0)
    assert [r.chunk_id for r in fused[:3]] == [r.chunk_id for r in DENSE]


def test_fusion_lifts_a_chunk_both_searches_found() -> None:
    fused = weighted_fuse(DENSE, SPARSE, rrf_k=60, sparse_weight=1.0)
    assert fused[0].chunk_id == "1:0:0"
    assert fused[1].chunk_id == "2:0:0"


def test_fusion_marks_a_keyword_only_chunk_as_unseen_by_dense() -> None:
    """`score = 0.0` means "the dense search never saw it", not "no match"."""
    fused = weighted_fuse(DENSE, SPARSE, rrf_k=60, sparse_weight=1.0)
    keyword_only = next(r for r in fused if r.chunk_id == "9:0:0")
    assert keyword_only.score == 0.0
    assert keyword_only.sparse_score == 0.5


def test_union_never_displaces_a_dense_candidate() -> None:
    merged, window = union(DENSE, SPARSE, extra=1)
    assert [r.chunk_id for r in merged[:3]] == [r.chunk_id for r in DENSE]
    assert merged[3].chunk_id == "9:0:0"
    assert window == 4


def test_rank_for_orders_by_rerank_score() -> None:
    pool = Pool(
        dense=DENSE,
        sparse=[],
        rerank_scores={"1:0:0": 0.1, "2:0:0": 0.9, "3:0:0": 0.5},
    )
    ranked = rank_for(Config("dense", "dense"), pool)
    assert [r.chunk_id for r in ranked] == ["2:0:0", "3:0:0", "1:0:0"]


def test_rank_for_keeps_vector_order_without_a_reranker() -> None:
    pool = Pool(dense=DENSE, sparse=[], rerank_scores={})
    ranked = rank_for(Config("dense", "dense"), pool)
    assert [r.chunk_id for r in ranked] == [r.chunk_id for r in DENSE]


def test_a_config_is_scored_by_the_real_metric_code() -> None:
    question = Question(id="q", kind="easy", text="why?", expected=("2:0",))
    pool = Pool(dense=DENSE, sparse=[], rerank_scores={})
    summary = run_config(Config("dense", "dense"), [question], {"q": pool})
    assert summary.recall_at_5 == 1.0


def test_as_record_ranks_from_one() -> None:
    question = Question(id="q", kind="easy", text="why?", expected=("1:0",))
    record = as_record(question, DENSE)
    assert [item.rank for item in record.retrieved] == [1, 2, 3]


def test_control_matches_only_when_the_numbers_reproduce() -> None:
    question = Question(id="q", kind="easy", text="why?", expected=("2:0",))
    baseline = summarise([as_record(question, DENSE)])
    same = summarise([as_record(question, DENSE)])
    different = summarise([as_record(question, [result("7:0:0")])])

    assert control_matches(same, baseline)
    assert not control_matches(different, baseline)


def test_control_fails_rather_than_passes_when_a_metric_is_missing() -> None:
    """An unanswerable-only set has recall of None; that is not a match."""
    question = Question(id="q", kind="unanswerable", text="why?")
    empty = summarise([as_record(question, DENSE)])
    assert not control_matches(empty, empty)


def test_render_puts_the_control_first() -> None:
    question = Question(id="q", kind="easy", text="why?", expected=("2:0",))
    pool = {"q": Pool(dense=DENSE, sparse=[], rerank_scores={})}
    rows = [
        (config, run_config(config, [question], pool))
        for config in (Config("dense only (control)", "dense"), Config("fuse", "fuse"))
    ]
    assert "dense only (control)" in render(rows).splitlines()[2]
