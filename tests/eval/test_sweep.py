"""The sweep harness: the fusion maths, the control check, and the ordering."""

from collections.abc import Mapping, Sequence

from eurohistory_rag.eval.metrics import summarise
from eurohistory_rag.eval.questions import Question, Turn
from eurohistory_rag.eval.sweep import (
    Config,
    Pool,
    as_record,
    collect_pools,
    control_matches,
    rank_for,
    render,
    run_config,
    sweepable,
    union,
    weighted_fuse,
)
from eurohistory_rag.retrieval.search import SearchResult
from eurohistory_rag.retrieval.vectorstore import Hit
from tests.fakes import FakeEmbedder, FakeReranker


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


def test_rank_for_thins_by_the_config_rather_than_the_module_constant() -> None:
    """D-082's arms only exist if the Config's caps reach `thin`.

    Three sections of article 1 satisfy the section cap, so only an article cap
    can separate these two rows -- which is the whole question being swept.
    """
    crowded = [result("1:0:0"), result("1:1:0"), result("1:2:0"), result("2:0:0")]
    pool = Pool(dense=crowded, sparse=[], rerank_scores={})

    default = rank_for(Config("dense", "dense"), pool)
    capped = rank_for(Config("article cap 1", "dense", max_per_article=1), pool)

    assert [r.chunk_id for r in default] == [r.chunk_id for r in crowded]
    assert [r.chunk_id for r in capped] == ["1:0:0", "2:0:0"]


def test_a_config_with_no_caps_keeps_every_candidate() -> None:
    """The arm arguing the rule should go: the best k, whatever they are."""
    crowded = [result("1:0:0", doc_id="1:0"), result("1:0:1", doc_id="1:0")]
    pool = Pool(dense=crowded, sparse=[], rerank_scores={})
    uncapped = Config("no cap at all", "dense", max_per_document=None)
    assert len(rank_for(uncapped, pool)) == 2
    assert len(rank_for(Config("dense", "dense"), pool)) == 2


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


def test_rerank_off_keeps_vector_order_even_when_scores_exist() -> None:
    """Phase 32's arm. The scores are present and are deliberately ignored.

    Distinct from `test_rank_for_keeps_vector_order_without_a_reranker`, which
    passes because there is nothing to sort by. This one proves the *setting*
    is doing the work: same pool, same scores, the only difference is the flag.
    """
    pool = Pool(
        dense=DENSE,
        sparse=[],
        rerank_scores={"1:0:0": 0.1, "2:0:0": 0.9, "3:0:0": 0.5},
    )

    assert [r.chunk_id for r in rank_for(Config("on", "dense"), pool)] == [
        "2:0:0",
        "3:0:0",
        "1:0:0",
    ]
    assert [
        r.chunk_id for r in rank_for(Config("off", "dense", rerank=False), pool)
    ] == [r.chunk_id for r in DENSE]


def test_rerank_off_still_attaches_the_scores_it_did_not_use() -> None:
    """So a table read afterwards can ask what the reranker would have done."""
    pool = Pool(dense=DENSE, sparse=[], rerank_scores={"2:0:0": 0.9})
    ranked = rank_for(Config("off", "dense", rerank=False), pool)

    assert {r.chunk_id: r.rerank_score for r in ranked}["2:0:0"] == 0.9


class NullStore:
    """A store that returns nothing and records nothing but the call."""

    def search(self, vector: Sequence[float], limit: int) -> list[Hit]:
        return []

    def search_sparse(self, sparse: Mapping[int, float], limit: int) -> list[Hit]:
        return []


def test_a_replacement_query_is_embedded_but_never_reranked() -> None:
    """HyDE's contract, and the easiest thing here to get quietly wrong.

    The made-up passage is what the *vector search* runs on. The cross-encoder
    must still see the reader's question, because that is what the real system
    shows it -- a sweep that reranked against the hypothesis would be measuring
    a system nobody runs.
    """
    question = Question(
        id="q", kind="paraphrase", text="the real question", expected=("1:0",)
    )
    embedder = FakeEmbedder()
    reranker = FakeReranker()

    collect_pools(
        [question],
        embedder,
        NullStore(),
        reranker,
        queries={"q": "a made-up encyclopedia passage"},
    )

    assert embedder.calls == [["a made-up encyclopedia passage"]]
    # Nothing was found, so the reranker had nothing to score and was never
    # called -- which is exactly why the embedder's call is the assertion that
    # matters. The store returning nothing keeps this test off the network.
    assert reranker.calls == []


def test_without_a_replacement_the_question_itself_is_embedded() -> None:
    """The default path, pinned so the HyDE parameter cannot change it."""
    question = Question(
        id="q", kind="paraphrase", text="the real question", expected=("1:0",)
    )
    embedder = FakeEmbedder()

    collect_pools([question], embedder, NullStore())

    assert embedder.calls == [["the real question"]]


def test_sweepable_drops_questions_the_harness_cannot_reproduce() -> None:
    """A conversation question is searched here on text no run ever embedded."""
    plain = Question(id="a", kind="paraphrase", text="q", expected=("1:0",))
    unanswerable = Question(id="b", kind="unanswerable", text="q")
    follow_up = Question(
        id="c",
        kind="paraphrase",
        text="and after that?",
        expected=("1:0",),
        suite="conversation",
        history=(Turn(user="earlier", assistant="answer"),),
    )

    assert [q.id for q in sweepable([plain, unanswerable, follow_up])] == ["a"]


def test_sweepable_narrows_to_one_kind() -> None:
    """Paraphrase is 16 of 92; the total cannot see it move."""
    para = Question(id="a", kind="paraphrase", text="q", expected=("1:0",))
    easy = Question(id="b", kind="easy", text="q", expected=("1:0",))

    assert [q.id for q in sweepable([para, easy], "paraphrase")] == ["a"]
