"""Gold to Qdrant: read chunks, embed them, weight their words, store them.

A pipeline stage like `silver` and `chunk`, and it belongs here rather than in
`core/` because only the CLI runs it. The two things it needs -- an embedder
and a store -- are passed in rather than built here, which is what lets the
tests run it end to end with a fake embedder and an in-memory Qdrant.

Rebuilds whole by default. Chunk ids move whenever chunk size changes, so
upserting into an existing collection would leave points nothing overwrites.
`resume` is the exception, for picking up an interrupted run.
"""

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from eurohistory_rag.retrieval.embedding import MAX_TEXTS_PER_REQUEST, Embedder
from eurohistory_rag.retrieval.sparse import (
    average_length,
    document_vector,
    tokenize,
)
from eurohistory_rag.retrieval.vectorstore import VectorStore

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 200


@dataclass(frozen=True, slots=True)
class IndexReport:
    """What one indexing run did."""

    indexed: int
    skipped: int
    points: int


def read_chunks(root: Path) -> pl.DataFrame:
    """The Gold table.

    Not sorted: Gold is already written in a stable order, and the order has to
    stay stable across runs or `resume` would skip the wrong batches.
    """
    return pl.read_parquet(root / "chunks.parquet")


def to_payload(row: dict[str, Any]) -> dict[str, Any]:
    """The metadata that travels with one vector.

    Ten of Gold's eleven columns. `license` is left out because it is the same
    string on every row -- the API states it once instead of storing 30,000
    copies. Everything else is here to show a hit, cite it, or filter on it;
    whatever is missing cannot be added without re-indexing. See D-044.
    """
    return {
        "chunk_id": row["chunk_id"],
        "doc_id": row["doc_id"],
        "page_id": row["page_id"],
        "position": row["position"],
        "title": row["title"],
        "heading": row["heading"],
        "text": row["text"],
        "themes": list(row["themes"]),
        "revision_id": row["revision_id"],
        # ISO text rather than a datetime: payloads are JSON, and Qdrant reads
        # this format back for range filters.
        "revision_timestamp": row["revision_timestamp"].isoformat(),
        **date_payload(row),
    }


def date_payload(row: dict[str, Any]) -> dict[str, Any]:
    """The period keys, present only when the chunk has a period.

    Omitted rather than written as null, and that is the whole design of the
    temporal filter in one line: Qdrant's range condition does not match a point
    whose field is absent, so an undated chunk simply never appears in the
    temporal arm's results. It is not excluded from anything -- the dense and
    keyword arms never look at these keys. See D-096.
    """
    if row["year_start"] is None:
        return {}
    return {
        "year_start": int(row["year_start"]),
        "year_end": int(row["year_end"]),
        "year_source": row["year_source"],
    }


def refresh_payloads(
    gold_root: Path, store: VectorStore, batch_size: int = DEFAULT_BATCH_SIZE
) -> IndexReport:
    """Rewrite every point's metadata from Gold, without embedding anything.

    The cheap half of `build`. A payload column added after the corpus was
    indexed -- Phase 22's year span is the first -- does not need new vectors,
    and paying for them would buy nothing but a fourth-decimal change in every
    cosine score at the exact moment two runs have to be compared.

    Only valid while `chunk_id` is unchanged, which is why it reports the point
    count: a Gold table rebuilt at a different chunk size produces ids that are
    not in the collection, Qdrant skips them, and the count is what says so.
    """
    started = time.monotonic()
    chunks = read_chunks(gold_root)
    logger.info("payload refresh: %d chunks", chunks.height)

    updated = 0
    for offset in range(0, chunks.height, batch_size):
        batch = chunks.slice(offset, batch_size)
        store.set_payload(
            batch["chunk_id"].to_list(),
            [to_payload(row) for row in batch.iter_rows(named=True)],
        )
        updated += batch.height
        logger.info("payload batch at %d: %d updated", offset, updated)

    for field in ("year_start", "year_end"):
        store.index_payload_field(field)

    points = store.count()
    logger.info(
        "payload refresh done: %d updated, %d points in %.1fs",
        updated,
        points,
        time.monotonic() - started,
    )
    return IndexReport(indexed=updated, skipped=0, points=points)


def build(
    gold_root: Path,
    store: VectorStore,
    embedder: Embedder,
    batch_size: int = DEFAULT_BATCH_SIZE,
    *,
    resume: bool = False,
) -> IndexReport:
    """Embed every chunk in Gold and write it to the store."""
    if not 0 < batch_size <= MAX_TEXTS_PER_REQUEST:
        raise ValueError(
            f"batch_size must be 1..{MAX_TEXTS_PER_REQUEST}, got {batch_size}"
        )

    started = time.monotonic()
    chunks = read_chunks(gold_root)
    store.ensure_collection(recreate=not resume)

    # BM25 judges a chunk's length against the corpus average, so that average
    # has to exist before the first chunk can be weighted. Measured here rather
    # than inside the loop on purpose: a per-batch average would weight the same
    # chunk differently depending on which batch it fell into, and `resume`
    # would then produce a collection no single run could reproduce. The price
    # is tokenising twice, which is a regex over text already in memory.
    average = average_length(tokenize(text) for text in chunks["text"])

    logger.info(
        "start: %d chunks, batch=%d, resume=%s, avg %.0f tokens",
        chunks.height,
        batch_size,
        resume,
        average,
    )

    indexed = 0
    skipped = 0
    for offset in range(0, chunks.height, batch_size):
        batch = chunks.slice(offset, batch_size)
        chunk_ids = batch["chunk_id"].to_list()

        if resume and store.has_all(chunk_ids):
            skipped += len(chunk_ids)
            continue

        texts = batch["text"].to_list()
        vectors = embedder.embed(texts)
        sparse_vectors = [document_vector(tokenize(text), average) for text in texts]
        payloads = [to_payload(row) for row in batch.iter_rows(named=True)]
        store.upsert(chunk_ids, vectors, sparse_vectors, payloads)

        indexed += len(chunk_ids)
        logger.info("batch at %d: %d indexed, %d skipped", offset, indexed, skipped)

    points = store.count()
    logger.info(
        "done: %d indexed, %d skipped, %d points in %.1fs",
        indexed,
        skipped,
        points,
        time.monotonic() - started,
    )
    return IndexReport(indexed=indexed, skipped=skipped, points=points)
