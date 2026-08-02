"""Silver to Gold: read, chunk, write.

Mirrors `silver/build.py` deliberately. Gold is a cache like Silver -- written
whole, overwritten whole, and rebuilt rather than resumed -- so there is no
partitioning and no idempotency logic here.
"""

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from eurohistory_rag.pipeline.gold.chunk import chunk_document
from eurohistory_rag.pipeline.gold.store import Chunk, to_frame, write
from eurohistory_rag.pipeline.silver.store import SilverRow

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BuildReport:
    """What one build did. `chunks` is the number the Phase 4 gate is read from."""

    documents: int
    chunks: int
    path: Path


def read_documents(root: Path) -> pl.DataFrame:
    """The Silver table, in a stable order.

    Sorted so that two builds of the same Silver table produce chunks in the
    same order, which makes a diff between two chunking settings readable.
    """
    return pl.read_parquet(root / "documents.parquet").sort("page_id", "position")


def to_document(row: dict[str, Any]) -> SilverRow:
    """One Parquet row back into the dataclass `chunk_document` expects.

    The cost of chunking taking a `SilverRow` rather than a narrower type:
    fields it never reads still have to be rebuilt. Cheap at this row count,
    and it keeps the dependency between the two layers explicit.
    """
    return SilverRow(
        doc_id=row["doc_id"],
        page_id=row["page_id"],
        position=row["position"],
        title=row["title"],
        heading=row["heading"],
        text=row["text"],
        themes=tuple(row["themes"]),
        link_targets=tuple(row["link_targets"]),
        categories=tuple(row["categories"]),
        infobox_type=row["infobox_type"],
        infobox=tuple((field["key"], field["value"]) for field in row["infobox"]),
        revision_id=row["revision_id"],
        revision_timestamp=row["revision_timestamp"],
        license=row["license"],
    )


def build(silver_root: Path, gold_root: Path, size: int, overlap: int) -> BuildReport:
    """Rebuild the whole Gold table from Silver.

    `size` and `overlap` are arguments rather than constants read here, so
    Phase 7 can re-chunk the corpus at a different setting from one command.
    """
    started = time.monotonic()
    documents = read_documents(silver_root)
    logger.info(
        "start: %d documents, size=%d, overlap=%d", documents.height, size, overlap
    )

    chunks: list[Chunk] = []
    for row in documents.iter_rows(named=True):
        chunks.extend(chunk_document(to_document(row), size, overlap))

    frame = to_frame(chunks)
    path = write(gold_root, frame)
    logger.info(
        "done: %d chunks from %d documents in %.1fs",
        frame.height,
        documents.height,
        time.monotonic() - started,
    )
    return BuildReport(documents=documents.height, chunks=frame.height, path=path)
