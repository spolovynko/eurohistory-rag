"""Question in, chunks out.

The recipe every caller shares: embed the question, ask the store, tidy the
result. It exists so /search and Phase 6's /ask do not each carry their own
copy of those three steps, and so neither of them ever sees a Qdrant object.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace

from eurohistory_rag.core.trace import Trace
from eurohistory_rag.retrieval.embedding import Embedder
from eurohistory_rag.retrieval.rerank import Reranker, RerankUnavailable
from eurohistory_rag.retrieval.sparse import query_vector
from eurohistory_rag.retrieval.temporal import parse_period
from eurohistory_rag.retrieval.vectorstore import Hit, VectorStore

logger = logging.getLogger(__name__)

# How many results a caller gets by default. Small enough that every one fits
# in an answer prompt, large enough that a question needing two sources works.
DEFAULT_K = 5

# At most this many chunks from any one section. Chunks overlap, so neighbours
# score almost identically and would otherwise fill the list with one page.
MAX_PER_DOCUMENT = 2

# At most this many chunks from any one article, or None for no limit. None is
# the default because the cap has now been measured twice -- D-082 on three
# themes and D-100 on nine -- and coverage@5 fell at every value both times.
# It is a setting rather than a constant so the arm can be run again without a
# code change, which is the only reason D-100 could re-run D-082 for nothing.
MAX_PER_ARTICLE: int | None = None

# Ask the store for this many times k, then thin down. Qdrant is no slower
# returning 20 than 5, and thinning needs spares to draw from.
OVERFETCH = 4

# How many candidates the reranker scores. Fixed rather than derived from k,
# because OVERFETCH multiplies k: the answer path asks for 5 and gets a pool of
# 20, while the eval asks for 20 and would get 80. Reranking a different pool
# in each would make the eval measure something the system never does. 20 is
# provably enough -- the Phase 7 baseline put recall@20 at 100%.
RERANK_TOP_N = 20

# The "do not over-trust first place" dial in reciprocal rank fusion. A chunk
# scores 1/(RRF_K + rank) in each list and the two are added. At 0, rank 1 is
# worth double rank 2; at 60 the two are nearly equal, so a chunk that both
# searches like beats one that only the dense search loves. 60 is the value
# from the original paper, kept because nothing here yet argues for another.
RRF_K = 60


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One matching chunk, in this project's terms.

    Carries what a citation needs plus the score. `themes` and
    `revision_timestamp` are deliberately absent: they live in the payload so
    Qdrant can filter on them, not so results can display them.

    `score` is always the cosine score and never anything else. A chunk the
    keyword search found but the dense search did not carries `score = 0.0`,
    which means "the dense search never saw it" rather than "orthogonal to the
    question" -- its real cosine score is unknown and would cost another round
    trip to learn.
    """

    chunk_id: str
    doc_id: str
    page_id: int
    title: str
    heading: str
    text: str
    score: float
    revision_id: int
    rerank_score: float | None = None
    # BM25's score, present only when the keyword search found this chunk. The
    # two scales are not comparable and are deliberately not merged: reading a
    # result afterwards, "which search found this, and how strongly" is the
    # question worth answering, and one blended number cannot answer it.
    sparse_score: float | None = None
    # The years this chunk covers, or None for the 28% that name none. Read from
    # the payload so the period arm can be ordered by how well each chunk's span
    # agrees with the question's, which Qdrant's filter cannot express.
    year_start: int | None = None
    year_end: int | None = None

    @property
    def source(self) -> str:
        """Human-readable location, e.g. "Berlin — History".

        A lead section has no heading, so the title stands alone rather than
        trailing an empty dash.
        """
        return f"{self.title} — {self.heading}" if self.heading else self.title

    @property
    def url(self) -> str:
        """Permanent link to the exact revision this text came from.

        `oldid` rather than the article URL: Wikipedia changes, and a citation
        that points at today's article cannot be checked against what was
        actually indexed.
        """
        return f"https://en.wikipedia.org/w/index.php?oldid={self.revision_id}"


def to_result(hit: Hit) -> SearchResult:
    """One store hit as a result. The only place payload keys are read."""
    payload = hit.payload
    return SearchResult(
        chunk_id=payload["chunk_id"],
        doc_id=payload["doc_id"],
        page_id=payload["page_id"],
        title=payload["title"],
        heading=payload["heading"],
        text=payload["text"],
        score=hit.score,
        revision_id=payload["revision_id"],
        # `.get`, not `[]`: an undated chunk has no such key, and a collection
        # indexed before Phase 22 has it on no chunk at all.
        year_start=payload.get("year_start"),
        year_end=payload.get("year_end"),
    )


def fuse(
    dense: Sequence[SearchResult],
    sparse: Sequence[SearchResult],
    rrf_k: int = RRF_K,
    period: Sequence[SearchResult] = (),
) -> list[SearchResult]:
    """Merge the ranked lists into one, by position rather than by score.

    Reciprocal rank fusion: a chunk earns `1 / (rrf_k + rank)` in each list it
    appears in, and the two are added. Positions rather than scores because
    cosine returns about 0.58 for a strong match and BM25 returns about 14 --
    numbers on different scales that cannot be added, and whose normalisation
    would be a guess. A rank is comparable by construction.

    What it buys: a chunk both searches like outranks one that only the dense
    search loves. That is the Trianon failure -- meaning-search buries it under
    Versailles sections, keyword-search puts it first, and agreement lifts it.

    `period` is D-096's third arm: the same dense search, restricted to chunks
    whose years overlap the question's. It is empty whenever the question names
    no period, which is 43 of the 78 evaluation questions, and when it is empty
    this function does exactly what it did before. A chunk that is right on both
    meaning and period appears in two lists and is lifted; a chunk with no date
    is scored by the other arms alone and is never removed.

    Ties keep dense order, because Python's sort is stable and dense goes in
    first. That matters only when nothing has been found twice.
    """
    fused: dict[str, float] = {}
    merged: dict[str, SearchResult] = {}

    for rank, result in enumerate(dense, start=1):
        fused[result.chunk_id] = fused.get(result.chunk_id, 0.0) + 1 / (rrf_k + rank)
        merged[result.chunk_id] = result

    for rank, result in enumerate(period, start=1):
        fused[result.chunk_id] = fused.get(result.chunk_id, 0.0) + 1 / (rrf_k + rank)
        # Same vector search, so a chunk found here carries the same cosine
        # score it would have carried from the dense arm. Nothing to reconcile.
        merged.setdefault(result.chunk_id, result)

    for rank, result in enumerate(sparse, start=1):
        fused[result.chunk_id] = fused.get(result.chunk_id, 0.0) + 1 / (rrf_k + rank)
        already = merged.get(result.chunk_id)
        merged[result.chunk_id] = (
            replace(already, sparse_score=result.score)
            if already is not None
            # Found by keyword alone: its cosine score is not known, so the
            # BM25 score moves to the field that means BM25 and `score` is
            # left at the "dense never saw it" value.
            else replace(result, score=0.0, sparse_score=result.score)
        )

    return sorted(merged.values(), key=lambda r: fused[r.chunk_id], reverse=True)


def thin(
    results: list[SearchResult],
    k: int,
    max_per_document: int | None,
    max_per_article: int | None = None,
) -> list[SearchResult]:
    """Keep the best `k`, capped per section and optionally per article.

    Order is preserved, so this only ever removes. If thinning cannot fill `k`
    the short list is returned rather than reinstating duplicates -- five slots
    holding three distinct sources beats five holding one page three times.

    `None` means no cap, on either limit. The section cap accepts it so D-082
    can measure removing the rule entirely, which is the arm arguing that a long
    article may genuinely hold the best five chunks.

    `max_per_article` is off by default, so nothing changes until the D-082
    sweep says it should. It exists because `doc_id` is a *section* and an
    article has many: capping sections never stopped one article taking every
    slot, which is the Versailles-with-no-Trianon failure seen five times.
    """
    kept: list[SearchResult] = []
    sections: dict[str, int] = {}
    articles: dict[int, int] = {}
    for result in results:
        section_full = (
            max_per_document is not None
            and sections.get(result.doc_id, 0) >= max_per_document
        )
        article_full = (
            max_per_article is not None
            and articles.get(result.page_id, 0) >= max_per_article
        )
        if section_full or article_full:
            continue
        sections[result.doc_id] = sections.get(result.doc_id, 0) + 1
        articles[result.page_id] = articles.get(result.page_id, 0) + 1
        kept.append(result)
        if len(kept) == k:
            break
    return kept


class SearchService:
    """Finds the chunks that answer a question."""

    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        k: int = DEFAULT_K,
        max_per_document: int = MAX_PER_DOCUMENT,
        max_per_article: int | None = MAX_PER_ARTICLE,
        overfetch: int = OVERFETCH,
        reranker: Reranker | None = None,
        rerank_top_n: int = RERANK_TOP_N,
        hybrid: bool = True,
        rrf_k: int = RRF_K,
        temporal: bool = False,
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._k = k
        self._max_per_document = max_per_document
        self._max_per_article = max_per_article
        self._overfetch = overfetch
        self._reranker = reranker
        self._rerank_top_n = rerank_top_n
        self._hybrid = hybrid
        self._rrf_k = rrf_k
        self._temporal = temporal

    def search(
        self,
        question: str,
        k: int | None = None,
        min_score: float | None = None,
        trace: Trace | None = None,
    ) -> list[SearchResult]:
        """The best chunks for this question, best first."""
        return self.search_with_vector(question, k, min_score, trace)[0]

    def search_with_vector(
        self,
        question: str,
        k: int | None = None,
        min_score: float | None = None,
        trace: Trace | None = None,
    ) -> tuple[list[SearchResult], list[float]]:
        """The best chunks, and the vector the question was turned into.

        The vector is handed back for one caller: the semantic answer cache,
        which needs the question's *meaning* as a key and would otherwise embed
        the same string a second time -- a second API call, a second round trip,
        and a second chance for the two vectors to disagree. Returning the one
        that was already made is free and is the same vector retrieval used,
        which is the stronger argument of the two.

        Empty on an empty question, in both halves. `search` is the same call
        with the vector dropped, so there is one implementation and no way for
        the two to drift apart.

        `min_score` is off by default on purpose. A cut-off looks obviously
        useful and is impossible to choose honestly today: a strong match scores
        about 0.58 on one question and 0.42 on another. Phase 7 produces thirty
        questions with real scores, and that is when a number can be picked from
        evidence. Until then Phase 6's prompt does the refusing.

        `trace` is where the stages write down what they cost. A caller that
        passes none gets a throwaway, so there is no second code path and no
        `if trace is not None` anywhere below. A span is opened only for a stage
        that actually runs -- the fusion span is absent on a dense-only
        configuration, exactly as the fusion *call* is -- which is what makes
        "these two questions ran different stages" a fact worth checking rather
        than a constant. D-101.
        """
        question = question.strip()
        if not question:
            return [], []

        if trace is None:
            trace = Trace()

        limit = k if k is not None else self._k
        pool = limit * self._overfetch
        with trace.span("search") as whole:
            with trace.span("embed") as span:
                vector = self._embedder.embed([question])[0]
                span.note = f"{len(vector)} dims"
            with trace.span("dense") as span:
                results = [
                    to_result(hit) for hit in self._store.search(vector, limit=pool)
                ]
                span.note = f"{len(results)} of {pool} asked for"

            # Applied before fusion, while it still means what it says. After
            # fusion half the list may carry `score = 0.0` because the dense
            # search never saw it, and a cosine cut-off would silently delete
            # exactly the chunks hybrid search exists to find.
            if min_score is not None:
                results = [result for result in results if result.score >= min_score]

            keyword: list[SearchResult] = []
            dated: list[SearchResult] = []
            period = parse_period(question) if self._temporal else None

            if period is not None:
                with trace.span("temporal") as span:
                    found = [
                        to_result(hit)
                        for hit in self._store.search_within(
                            vector, limit=pool, start=period.start, end=period.end
                        )
                    ]
                    # Reordered by how closely each span agrees with the
                    # question's period, cosine breaking ties. Qdrant's range
                    # filter can only say whether two ranges touch, and a
                    # one-year touch arriving at rank 1 of this list earns the
                    # same fusion bonus as an exact match -- which is how the
                    # first build made the temporal suite worse. The list is
                    # only reordered, never shortened. See the D-096 addendum.
                    dated = sorted(
                        found,
                        key=lambda r: (
                            period.agreement(r.year_start, r.year_end),
                            r.score,
                        ),
                        reverse=True,
                    )
                    span.note = f"{len(dated)} within {period}"

            if self._hybrid:
                with trace.span("sparse") as span:
                    keyword = [
                        to_result(hit)
                        for hit in self._store.search_sparse(
                            query_vector(question), limit=pool
                        )
                    ]
                    span.note = f"{len(keyword)} candidates"

            # Fusion is skipped entirely when neither extra arm ran, so a
            # question naming no period on a dense-only configuration takes
            # exactly the code path it took before this phase -- same list,
            # same order, provably.
            if keyword or dated:
                with trace.span("fuse") as span:
                    results = fuse(results, keyword, self._rrf_k, period=dated)
                    span.note = f"{len(results)} merged"

            if self._reranker is not None:
                with trace.span("rerank") as span:
                    scored = min(self._rerank_top_n, len(results))
                    results = self._rerank(question, results)
                    span.note = f"{scored} of {len(results)} scored"

            with trace.span("thin") as span:
                thinned = thin(
                    results, limit, self._max_per_document, self._max_per_article
                )
                span.note = f"{len(thinned)} of {limit} slots"

            whole.note = f"{len(thinned)} chunks"

        logger.debug(
            "search %r: %d dense, %d keyword, %d in %s, %d after thinning",
            question,
            len(results),
            len(keyword),
            len(dated),
            period,
            len(thinned),
        )
        return thinned, vector

    def _rerank(self, question: str, results: list[SearchResult]) -> list[SearchResult]:
        """Reorder candidates by cross-encoder score, best first.

        Only the first `rerank_top_n` candidates are scored; anything below
        keeps its vector position and follows them. Returns the list untouched
        when reranking is off or unreachable: a missing model should degrade
        search to Phase 5's behaviour, not break it.
        """
        if self._reranker is None or not results:
            return results

        head = results[: self._rerank_top_n]
        tail = results[self._rerank_top_n :]
        try:
            scored = self._reranker.rerank(question, [r.text for r in head])
        except RerankUnavailable:
            logger.warning("reranker unavailable; keeping vector order")
            return results

        return [
            replace(head[index], rerank_score=score) for index, score in scored
        ] + tail
