"""The search service: what it hands back, and how it thins duplicates.

Runs against an in-process Qdrant and the fake embedder, so there is no network
and no Docker. `thin` is a plain function and is tested on its own -- it is the
only piece here with logic worth isolating.
"""

from collections.abc import Sequence
from typing import Any

from eurohistory_rag.retrieval.rerank import Reranker
from eurohistory_rag.retrieval.search import (
    SearchResult,
    SearchService,
    thin,
    to_result,
)
from eurohistory_rag.retrieval.sparse import (
    average_length,
    document_vector,
    tokenize,
)
from eurohistory_rag.retrieval.vectorstore import Hit, VectorStore
from tests.fakes import FakeEmbedder, FakeReranker, UnavailableReranker

# --- helpers ----------------------------------------------------------------


def result(chunk_id: str, doc_id: str, score: float = 0.5) -> SearchResult:
    """A result with only the fields `thin` looks at varied."""
    return SearchResult(
        chunk_id=chunk_id,
        doc_id=doc_id,
        page_id=30030,
        title="Marshall Plan",
        heading="Origins",
        text="Marshall plan aid to Europe.",
        score=score,
        revision_id=30130,
    )


def payload(chunk_id: str, heading: str = "Origins") -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "doc_id": "30030:1",
        "page_id": 30030,
        "title": "Marshall Plan",
        "heading": heading,
        "text": "Marshall plan aid to Europe.",
        "revision_id": 30130,
    }


class RecordingStore:
    """A store that remembers the limit it was asked for.

    Only used to check the over-fetch multiplier, which is invisible from the
    outside: the caller asks for 5 and the store is asked for 20.
    """

    def __init__(self) -> None:
        self.limits: list[int] = []

    def search(self, vector: Sequence[float], limit: int) -> list[Hit]:
        self.limits.append(limit)
        return []


def service_over(
    texts_by_doc: list[tuple[str, str, str]],
    reranker: Reranker | None = None,
    **kwargs: int,
) -> tuple[SearchService, FakeEmbedder]:
    """A service backed by a store holding the given (chunk_id, doc_id, text)."""
    embedder = FakeEmbedder()
    store = VectorStore.in_memory("chunks", embedder.dimensions)
    store.ensure_collection(recreate=True)
    chunk_ids = [chunk_id for chunk_id, _, _ in texts_by_doc]
    vectors = embedder.embed([text for _, _, text in texts_by_doc])
    payloads = [
        {**payload(chunk_id), "doc_id": doc_id, "text": text}
        for chunk_id, doc_id, text in texts_by_doc
    ]
    tokens = [tokenize(text) for _, _, text in texts_by_doc]
    average = average_length(tokens)
    sparse = [document_vector(token_list, average) for token_list in tokens]
    store.upsert(chunk_ids, vectors, sparse, payloads)
    return SearchService(embedder, store, reranker=reranker, **kwargs), embedder


# --- one result -------------------------------------------------------------


def test_a_hit_becomes_a_result() -> None:
    converted = to_result(Hit(score=0.61, payload=payload("30030:1:0")))
    assert converted.chunk_id == "30030:1:0"
    assert converted.title == "Marshall Plan"
    assert converted.score == 0.61


def test_the_source_line_joins_title_and_heading() -> None:
    assert result("a", "d").source == "Marshall Plan — Origins"


def test_a_lead_section_has_no_trailing_dash() -> None:
    """Silver stores "" for a lead section, so the title must stand alone."""
    lead = to_result(Hit(score=0.5, payload=payload("30030:0:0", heading="")))
    assert lead.source == "Marshall Plan"


def test_the_url_points_at_the_exact_revision_indexed() -> None:
    """An article URL would point at today's text, not what was embedded."""
    assert result("a", "d").url.endswith("oldid=30130")


# --- thinning ---------------------------------------------------------------


def test_thin_keeps_the_best_k() -> None:
    results = [result(f"c{i}", f"d{i}") for i in range(10)]
    assert [r.chunk_id for r in thin(results, k=3, max_per_document=2)] == [
        "c0",
        "c1",
        "c2",
    ]


def test_thin_allows_no_more_than_the_cap_from_one_section() -> None:
    """Overlapping neighbours score alike, so one section could fill the list."""
    results = [result(f"c{i}", "same") for i in range(5)]
    assert len(thin(results, k=5, max_per_document=2)) == 2


def test_thin_reaches_past_a_crowded_section_to_find_variety() -> None:
    results = [
        result("c0", "berlin"),
        result("c1", "berlin"),
        result("c2", "berlin"),
        result("c3", "germany"),
    ]
    kept = [r.chunk_id for r in thin(results, k=3, max_per_document=2)]
    assert kept == ["c0", "c1", "c3"]


def test_thin_returns_a_short_list_rather_than_reinstating_duplicates() -> None:
    """Three distinct sources beat five slots holding one page five times."""
    results = [result(f"c{i}", "same") for i in range(5)]
    assert len(thin(results, k=5, max_per_document=1)) == 1


def test_thin_never_reorders() -> None:
    results = [result("c0", "a"), result("c1", "b"), result("c2", "c")]
    assert [r.chunk_id for r in thin(results, k=3, max_per_document=1)] == [
        "c0",
        "c1",
        "c2",
    ]


# --- searching --------------------------------------------------------------


def test_an_empty_question_finds_nothing() -> None:
    service, _ = service_over([("c0", "d0", "Marshall plan aid.")])
    assert service.search("   ") == []


def test_a_question_finds_the_chunk_sharing_its_words() -> None:
    service, _ = service_over(
        [
            ("c0", "d0", "Berlin blockade and the airlift."),
            ("c1", "d1", "Treaty of Rome and the common market."),
        ]
    )
    hits = service.search("Berlin blockade", k=1)
    assert hits[0].text == "Berlin blockade and the airlift."


def test_a_search_returns_at_most_k() -> None:
    service, _ = service_over(
        [(f"c{i}", f"d{i}", f"Marshall plan paragraph {i}.") for i in range(10)]
    )
    assert len(service.search("Marshall plan", k=3)) == 3


def test_neighbouring_chunks_of_one_section_cannot_fill_the_results() -> None:
    """The duplicate problem, end to end: four chunks, one section."""
    service, _ = service_over(
        [(f"c{i}", "same-section", f"Marshall plan paragraph {i}.") for i in range(4)]
    )
    assert len(service.search("Marshall plan", k=4)) == 2


def test_the_store_is_asked_for_more_than_the_caller_wants() -> None:
    """Thinning needs spares to draw from, and Qdrant is no slower for 20."""
    store = RecordingStore()
    service = SearchService(FakeEmbedder(), store, overfetch=4)  # type: ignore[arg-type]
    service.search("Marshall plan", k=5)
    assert store.limits == [20]


def test_min_score_drops_weak_matches_when_asked() -> None:
    """Off by default: a good score on one question is a bad one on another."""
    service, _ = service_over(
        [
            ("c0", "d0", "Berlin blockade and the airlift."),
            ("c1", "d1", "A paragraph about nothing in the vocabulary."),
        ]
    )
    assert len(service.search("Berlin blockade", k=5)) == 2
    assert len(service.search("Berlin blockade", k=5, min_score=0.9)) == 1


# --- reranking --------------------------------------------------------------
#
# Every test here relies on FakeEmbedder and FakeReranker disagreeing: the
# embedder scores "Berlin blockade" highly and the reranker only counts "wall".
# That disagreement is the whole point -- if they agreed, a passing test could
# not tell reranking apart from reranking never having run.


DISAGREEING_CORPUS = [
    ("c0", "d0", "Berlin blockade and the Berlin airlift."),
    ("c1", "d1", "The Berlin blockade began in 1948."),
    ("c2", "d2", "A wall divided the city."),
]


def test_the_reranker_decides_the_final_order() -> None:
    """The wiring guard: without it, a dead reranker looks exactly like none."""
    service, _ = service_over(DISAGREEING_CORPUS, reranker=FakeReranker(term="wall"))
    assert service.search("Berlin blockade", k=3)[0].chunk_id == "c2"


def test_without_a_reranker_the_vector_order_stands() -> None:
    """The same corpus, unchanged behaviour -- this is the Phase 7 baseline."""
    service, _ = service_over(DISAGREEING_CORPUS)
    assert service.search("Berlin blockade", k=3)[0].chunk_id != "c2"


def test_the_reranker_sees_every_candidate_not_just_k() -> None:
    """The point of over-fetching: rank 3 by vector can become rank 1."""
    service, _ = service_over(DISAGREEING_CORPUS, reranker=FakeReranker(term="wall"))
    assert [r.chunk_id for r in service.search("Berlin blockade", k=1)] == ["c2"]


def test_the_reranker_is_given_the_question_and_the_chunk_texts() -> None:
    reranker = FakeReranker(term="wall")
    service, _ = service_over(DISAGREEING_CORPUS, reranker=reranker)
    service.search("Berlin blockade", k=3)
    question, documents = reranker.calls[0]
    assert question == "Berlin blockade"
    assert "A wall divided the city." in documents


def test_the_rerank_score_is_recorded_alongside_the_cosine_score() -> None:
    """Both are kept: the cosine number is what the Phase 7 baseline measured."""
    service, _ = service_over(DISAGREEING_CORPUS, reranker=FakeReranker(term="wall"))
    top = service.search("Berlin blockade", k=3)[0]
    assert top.rerank_score == 1.0
    assert 0.0 < top.score < 1.0


def test_the_rerank_score_is_none_when_reranking_is_off() -> None:
    service, _ = service_over(DISAGREEING_CORPUS)
    assert all(r.rerank_score is None for r in service.search("Berlin blockade", k=3))


def test_an_unreachable_reranker_degrades_to_the_vector_order() -> None:
    """A missing model should cost ranking quality, not the whole endpoint."""
    service, _ = service_over(DISAGREEING_CORPUS, reranker=UnavailableReranker())
    degraded = [r.chunk_id for r in service.search("Berlin blockade", k=3)]
    unranked, _ = service_over(DISAGREEING_CORPUS)
    assert degraded == [r.chunk_id for r in unranked.search("Berlin blockade", k=3)]


def test_only_the_top_candidates_are_reranked() -> None:
    """The pool is fixed at rerank_top_n, not derived from k.

    OVERFETCH multiplies k, so the answer path would rerank 20 and the eval 80.
    A reranker seeing a different pool in each makes the eval measure something
    production never does.
    """
    reranker = FakeReranker(term="wall")
    service, _ = service_over(
        [(f"c{i}", f"d{i}", "Berlin blockade.") for i in range(8)],
        reranker=reranker,
        rerank_top_n=3,
    )
    service.search("Berlin blockade", k=2)
    _, documents = reranker.calls[0]
    assert len(documents) == 3


def test_candidates_below_the_rerank_pool_keep_their_vector_position() -> None:
    """A chunk outside the pool must survive, unscored, below the reranked ones."""
    service, _ = service_over(
        DISAGREEING_CORPUS, reranker=FakeReranker(term="wall"), rerank_top_n=2
    )
    ranked = service.search("Berlin blockade", k=3)
    assert len(ranked) == 3
    assert ranked[-1].rerank_score is None


def test_reranking_happens_before_thinning() -> None:
    """Thinning trusts the order it is handed, so it has to run second.

    Two chunks of one section plus one of another. The reranker puts the
    section's chunks first and second; thinning caps that section at two, so
    all three survive only if the cap is applied to the reranked order.

    The counts have to differ by a whole word: both fakes split on whitespace,
    so a term ending a sentence is "wall." and does not count.
    """
    service, _ = service_over(
        [
            ("c0", "shared", "A wall and another wall stood here."),
            ("c1", "shared", "A wall stood here."),
            ("c2", "other", "Berlin blockade."),
        ],
        reranker=FakeReranker(term="wall"),
    )
    assert [r.chunk_id for r in service.search("Berlin blockade", k=3)] == [
        "c0",
        "c1",
        "c2",
    ]
