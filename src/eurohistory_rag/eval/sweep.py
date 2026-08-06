"""Many retrieval settings, measured in one pass, for the price of none.

Retrieval is free and perfectly repeatable -- Phase 8's accidental A/A run
matched every retrieval metric to four significant figures. Generation is
neither. recall, coverage and MRR need no model call, so a dozen configurations
cost one embedding per question instead of a dozen full evals.

Three things make it fast enough to be worth having:

  * every question is embedded once and its pools reused for every config;
  * the dense and keyword pools are fetched once at the widest depth any config
    asks for, then sliced;
  * the cross-encoder scores each (question, chunk) pair once and the score is
    cached -- a rerank score does not depend on the configuration that put the
    chunk in front of it.

**This is diagnosis, not a verdict.** Picking the best of N configurations on
the same questions that measure them is fitting the settings to the test. Read
the table for whether anything looks structurally different -- Phase 9's BM25
sweep was a monotone curve, and that is what made it an answer rather than a
scatter of noise.

**The first row is a control and it is not decoration.** It reproduces a run
already on disk. If it does not match that run, nothing below it means anything,
which is why `control_matches` is checked before the table is printed rather
than eyeballed afterwards.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace

from eurohistory_rag.eval.metrics import Summary, summarise
from eurohistory_rag.eval.questions import Question
from eurohistory_rag.eval.record import EvalRecord, Retrieved
from eurohistory_rag.retrieval.embedding import Embedder
from eurohistory_rag.retrieval.rerank import Reranker, RerankUnavailable
from eurohistory_rag.retrieval.search import (
    MAX_PER_DOCUMENT,
    RERANK_TOP_N,
    SearchResult,
    thin,
    to_result,
)
from eurohistory_rag.retrieval.sparse import query_vector
from eurohistory_rag.retrieval.vectorstore import VectorStore

logger = logging.getLogger(__name__)

# The widest pool any config asks for. Fetched once per question.
MAX_POOL = 100

# What the eval asks for: 20 results, judged at depths 5 and 20.
EVAL_K = 20

# How far two recall figures may differ and still count as the same run.
# Retrieval is deterministic, so this is zero in spirit; it exists only to
# survive float formatting.
CONTROL_TOLERANCE = 1e-6


@dataclass(frozen=True, slots=True)
class Config:
    """One candidate-generation setting to measure.

    `mode` is the structural choice and the interesting one:

    "dense"  -- today's system, and the control.
    "fuse"   -- what Phase 9 measured: reciprocal rank fusion reorders the whole
                pool, so a chunk the two searches disagree about can be pushed
                below the reranker's window entirely.
    "union"  -- fusion that can only add. The dense head is kept intact and
                keyword-only chunks are appended into an enlarged rerank
                window, so no dense candidate can be displaced.
    """

    name: str
    mode: str
    sparse_weight: float = 1.0
    sparse_pool: int = 80
    rrf_k: int = 60
    union_extra: int = 10


DEFAULT_CONFIGS = (
    Config("dense only (control)", "dense"),
    Config("fuse w=1.0", "fuse"),
    Config("fuse w=0.5", "fuse", sparse_weight=0.5),
    Config("fuse w=0.25", "fuse", sparse_weight=0.25),
    Config("fuse w=0.1", "fuse", sparse_weight=0.1),
    Config("union +5", "union", union_extra=5),
    Config("union +10", "union"),
)


@dataclass(frozen=True, slots=True)
class Pool:
    """Everything one question needs, fetched once and reused by every config."""

    dense: list[SearchResult]
    sparse: list[SearchResult]
    rerank_scores: dict[str, float]


def weighted_fuse(
    dense: Sequence[SearchResult],
    sparse: Sequence[SearchResult],
    rrf_k: int,
    sparse_weight: float,
) -> list[SearchResult]:
    """Reciprocal rank fusion with a thumb on the scale.

    Identical to `search.fuse` at `sparse_weight = 1.0`. The weight exists
    because the two searches are not equally good on this corpus and an equal
    vote is a claim rather than a default. At 0.0 it degenerates to dense
    order, so the sweep contains its own control by construction.
    """
    scores: dict[str, float] = {}
    merged: dict[str, SearchResult] = {}

    for rank, result in enumerate(dense, start=1):
        scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + 1 / (rrf_k + rank)
        merged[result.chunk_id] = result

    for rank, result in enumerate(sparse, start=1):
        scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + sparse_weight / (
            rrf_k + rank
        )
        already = merged.get(result.chunk_id)
        merged[result.chunk_id] = (
            replace(already, sparse_score=result.score)
            if already is not None
            else replace(result, score=0.0, sparse_score=result.score)
        )

    return sorted(merged.values(), key=lambda r: scores[r.chunk_id], reverse=True)


def union(
    dense: Sequence[SearchResult], sparse: Sequence[SearchResult], extra: int
) -> tuple[list[SearchResult], int]:
    """Keep the dense head whole and append keyword-only chunks behind it.

    Returns the candidate list and how many of them the reranker should score.
    The rerank window grows rather than being reallocated -- that is the whole
    idea: a keyword chunk earns a seat next to the dense ones instead of taking
    one from them.
    """
    head = list(dense[:RERANK_TOP_N])
    seen = {result.chunk_id for result in head}
    added = [
        replace(result, score=0.0, sparse_score=result.score)
        for result in sparse
        if result.chunk_id not in seen
    ][:extra]
    return head + added + list(dense[RERANK_TOP_N:]), len(head) + len(added)


def candidates(config: Config, pool: Pool) -> tuple[list[SearchResult], int]:
    """The ordered pool this config hands the reranker, and its window size."""
    if config.mode == "dense":
        return pool.dense, RERANK_TOP_N
    trimmed = pool.sparse[: config.sparse_pool]
    if config.mode == "union":
        return union(pool.dense, trimmed, config.union_extra)
    fused = weighted_fuse(pool.dense, trimmed, config.rrf_k, config.sparse_weight)
    return fused, RERANK_TOP_N


def rank_for(config: Config, pool: Pool) -> list[SearchResult]:
    """One config's final ranking for one question, reranked and thinned.

    Deliberately mirrors `SearchService.search`: rerank the head, leave the
    tail in candidate order, then thin. A sweep that ordered results some other
    way would be measuring a system nobody runs.
    """
    ordered, window = candidates(config, pool)
    head = sorted(
        (
            replace(result, rerank_score=pool.rerank_scores.get(result.chunk_id))
            for result in ordered[:window]
        ),
        key=lambda result: result.rerank_score or 0.0,
        reverse=True,
    )
    return thin(head + ordered[window:], EVAL_K, MAX_PER_DOCUMENT)


def as_record(question: Question, results: Sequence[SearchResult]) -> EvalRecord:
    """A record carrying retrieval only, so the real metric code can read it.

    Reusing `metrics.summarise` rather than recomputing recall here: a second
    implementation of a metric is a second chance to get it wrong, and Phase 7
    already shipped one metric that lied.
    """
    return EvalRecord(
        question_id=question.id,
        question=question.text,
        kind=question.kind,
        expected_doc_ids=list(question.expected),
        retrieved=[
            Retrieved(
                rank=rank,
                chunk_id=result.chunk_id,
                doc_id=result.doc_id,
                page_id=result.page_id,
                source=result.source,
                score=result.score,
                rerank_score=result.rerank_score,
                sparse_score=result.sparse_score,
            )
            for rank, result in enumerate(results, start=1)
        ],
        answer="",
        generation_model="",
        sources_sent=0,
        markers_found=[],
        citations=[],
        search_ms=0.0,
        generate_ms=0.0,
        total_ms=0.0,
    )


def collect_pools(
    questions: Sequence[Question],
    embedder: Embedder,
    store: VectorStore,
    reranker: Reranker | None = None,
    max_pool: int = MAX_POOL,
) -> dict[str, Pool]:
    """Fetch and rerank every question's candidates once.

    The only function here that touches the network, which is what lets
    everything above it be tested with no Qdrant, no API key and no weights.
    """
    pools: dict[str, Pool] = {}
    for position, question in enumerate(questions, start=1):
        vector = embedder.embed([question.text])[0]
        dense = [to_result(hit) for hit in store.search(vector, limit=max_pool)]
        sparse = [
            to_result(hit)
            for hit in store.search_sparse(query_vector(question.text), limit=max_pool)
        ]

        texts = {result.chunk_id: result.text for result in [*dense, *sparse]}
        scores: dict[str, float] = {}
        if reranker is not None and texts:
            chunk_ids = list(texts)
            try:
                scored = reranker.rerank(question.text, [texts[i] for i in chunk_ids])
                scores = {chunk_ids[index]: score for index, score in scored}
            except RerankUnavailable:
                logger.warning("reranker unavailable; sweeping in vector order")

        pools[question.id] = Pool(dense=dense, sparse=sparse, rerank_scores=scores)
        logger.info("[%d/%d] %s", position, len(questions), question.id)
    return pools


def run_config(
    config: Config, questions: Sequence[Question], pools: dict[str, Pool]
) -> Summary:
    """One config's numbers over the whole question set."""
    records = [
        as_record(question, rank_for(config, pools[question.id]))
        for question in questions
        if question.id in pools
    ]
    return summarise(records)


def sweep(
    configs: Sequence[Config], questions: Sequence[Question], pools: dict[str, Pool]
) -> list[tuple[Config, Summary]]:
    """Every config, measured against the same pools."""
    return [(config, run_config(config, questions, pools)) for config in configs]


def control_matches(
    control: Summary, baseline: Summary, tolerance: float = CONTROL_TOLERANCE
) -> bool:
    """Does the control row reproduce a run already on disk?

    Compares recall at both depths and MRR. If the harness cannot reproduce a
    known result then every other row is a number from a machine nobody has
    checked, and Phase 9's sweep was only believable because two of its rows
    were reproductions rather than measurements.
    """
    pairs = (
        (control.recall_at_5, baseline.recall_at_5),
        (control.recall_at_20, baseline.recall_at_20),
        (control.mrr, baseline.mrr),
    )
    return all(
        got is not None and want is not None and abs(got - want) <= tolerance
        for got, want in pairs
    )


def render(rows: Sequence[tuple[Config, Summary]]) -> str:
    """The sweep table, one row per config."""
    header = (
        f"{'config':<22} {'r@5':>7} {'r@20':>7} {'cov@5':>7} {'MRR':>6} {'arts':>6}"
    )
    lines = [header, "-" * len(header)]
    for config, summary in rows:
        lines.append(
            f"{config.name:<22} "
            f"{(summary.recall_at_5 or 0):>7.1%} {(summary.recall_at_20 or 0):>7.1%} "
            f"{(summary.coverage_at_5 or 0):>7.1%} {(summary.mrr or 0):>6.2f} "
            f"{summary.mean_distinct_articles_at_5:>6.1f}"
        )
    return "\n".join(lines)
