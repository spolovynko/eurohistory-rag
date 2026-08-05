"""Question in, chunks out.

The recipe every caller shares: embed the question, ask the store, tidy the
result. It exists so /search and Phase 6's /ask do not each carry their own
copy of those three steps, and so neither of them ever sees a Qdrant object.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace

from eurohistory_rag.retrieval.embedding import Embedder
from eurohistory_rag.retrieval.rerank import Reranker, RerankUnavailable
from eurohistory_rag.retrieval.sparse import query_vector
from eurohistory_rag.retrieval.vectorstore import Hit, VectorStore

logger = logging.getLogger(__name__)

# How many results a caller gets by default. Small enough that every one fits
# in an answer prompt, large enough that a question needing two sources works.
DEFAULT_K = 5

# At most this many chunks from any one section. Chunks overlap, so neighbours
# score almost identically and would otherwise fill the list with one page.
MAX_PER_DOCUMENT = 2

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
    )


def fuse(
    dense: Sequence[SearchResult],
    sparse: Sequence[SearchResult],
    rrf_k: int = RRF_K,
) -> list[SearchResult]:
    """Merge the two ranked lists into one, by position rather than by score.

    Reciprocal rank fusion: a chunk earns `1 / (rrf_k + rank)` in each list it
    appears in, and the two are added. Positions rather than scores because
    cosine returns about 0.58 for a strong match and BM25 returns about 14 --
    numbers on different scales that cannot be added, and whose normalisation
    would be a guess. A rank is comparable by construction.

    What it buys: a chunk both searches like outranks one that only the dense
    search loves. That is the Trianon failure -- meaning-search buries it under
    Versailles sections, keyword-search puts it first, and agreement lifts it.

    Ties keep dense order, because Python's sort is stable and dense goes in
    first. That matters only when nothing has been found twice.
    """
    fused: dict[str, float] = {}
    merged: dict[str, SearchResult] = {}

    for rank, result in enumerate(dense, start=1):
        fused[result.chunk_id] = fused.get(result.chunk_id, 0.0) + 1 / (rrf_k + rank)
        merged[result.chunk_id] = result

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
    results: list[SearchResult], k: int, max_per_document: int
) -> list[SearchResult]:
    """Keep the best `k`, allowing at most `max_per_document` from one section.

    Order is preserved, so this only ever removes. If thinning cannot fill `k`
    the short list is returned rather than reinstating duplicates -- five slots
    holding three distinct sources beats five holding one page three times.
    """
    kept: list[SearchResult] = []
    seen: dict[str, int] = {}
    for result in results:
        if seen.get(result.doc_id, 0) >= max_per_document:
            continue
        seen[result.doc_id] = seen.get(result.doc_id, 0) + 1
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
        overfetch: int = OVERFETCH,
        reranker: Reranker | None = None,
        rerank_top_n: int = RERANK_TOP_N,
        hybrid: bool = True,
        rrf_k: int = RRF_K,
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._k = k
        self._max_per_document = max_per_document
        self._overfetch = overfetch
        self._reranker = reranker
        self._rerank_top_n = rerank_top_n
        self._hybrid = hybrid
        self._rrf_k = rrf_k

    def search(
        self,
        question: str,
        k: int | None = None,
        min_score: float | None = None,
    ) -> list[SearchResult]:
        """The best chunks for this question, best first.

        `min_score` is off by default on purpose. A cut-off looks obviously
        useful and is impossible to choose honestly today: a strong match scores
        about 0.58 on one question and 0.42 on another. Phase 7 produces thirty
        questions with real scores, and that is when a number can be picked from
        evidence. Until then Phase 6's prompt does the refusing.
        """
        question = question.strip()
        if not question:
            return []

        limit = k if k is not None else self._k
        pool = limit * self._overfetch
        vector = self._embedder.embed([question])[0]
        results = [to_result(hit) for hit in self._store.search(vector, limit=pool)]

        # Applied before fusion, while it still means what it says. After
        # fusion half the list may carry `score = 0.0` because the dense search
        # never saw it, and a cosine cut-off would silently delete exactly the
        # chunks hybrid search exists to find.
        if min_score is not None:
            results = [result for result in results if result.score >= min_score]

        keyword: list[SearchResult] = []
        if self._hybrid:
            keyword = [
                to_result(hit)
                for hit in self._store.search_sparse(query_vector(question), limit=pool)
            ]
            results = fuse(results, keyword, self._rrf_k)

        results = self._rerank(question, results)

        thinned = thin(results, limit, self._max_per_document)
        logger.debug(
            "search %r: %d dense, %d keyword, %d after thinning",
            question,
            len(results),
            len(keyword),
            len(thinned),
        )
        return thinned

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
