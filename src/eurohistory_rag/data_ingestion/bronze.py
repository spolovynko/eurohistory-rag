"""Bronze: raw wikitext plus provenance. Immutable and append-only."""

import datetime as dt
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

import polars as pl
from polars.datatypes import DataType, DataTypeClass

from eurohistory_rag.data_ingestion.wikipedia import Revision

LICENSE = "CC BY-SA 4.0"
_COLUMNS: dict[str, DataType | DataTypeClass] = {
    "page_id": pl.Int64,  # primary key: titles get renamed, ids do not
    "title": pl.Utf8,  # resolved, after redirects
    "requested_title": pl.Utf8,  # what the registry asked for
    "theme": pl.Utf8,
    "revision_id": pl.Int64,  # the version pin
    "revision_timestamp": pl.Datetime("us", "UTC"),  # last edited
    "wikitext": pl.Utf8,
    "fetched_at": pl.Datetime("us", "UTC"),  # when we downloaded it
    "license": pl.Utf8,
}

BRONZE_SCHEMA = pl.Schema(_COLUMNS)


def to_frame(
    revisions: Sequence[Revision], theme: str, fetched_at: dt.datetime
) -> pl.DataFrame:
    """Build one Bronze frame from a batch of revisions."""
    return pl.DataFrame(
        [
            {
                "page_id": r.page_id,
                "title": r.title,
                "requested_title": r.requested_title,
                "theme": theme,
                "revision_id": r.revision_id,
                "revision_timestamp": r.revision_timestamp,
                "wikitext": r.wikitext,
                "fetched_at": fetched_at,
                "license": LICENSE,
            }
            for r in revisions
        ],
        schema=BRONZE_SCHEMA,
    )


def partition_path(root: Path, fetched_at: dt.datetime) -> Path:
    """One directory per ingest day: data/bronze/ingest_date=2026-07-31/."""
    return root / f"ingest_date={fetched_at.date().isoformat()}"


def write_batch(root: Path, frame: pl.DataFrame, fetched_at: dt.datetime) -> Path:
    """Append one batch as its own Parquet file.

    A new file per batch, never a rewrite. That is what makes Bronze append-only
    in practice: a crash mid-run leaves every already-written file complete and
    readable, and nothing that exists is ever touched again.
    """
    directory = partition_path(root, fetched_at)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"part-{uuid4().hex[:12]}.parquet"
    frame.write_parquet(path)
    return path


def ingested_keys(root: Path) -> set[tuple[str, str]]:
    """(theme, requested_title) pairs already in Bronze, for skipping on resume."""
    if not root.exists() or not any(root.rglob("*.parquet")):
        return set()
    frame = (
        pl.scan_parquet(root / "**" / "*.parquet")
        .select("theme", "requested_title")
        .collect()
    )
    return set(zip(frame["theme"], frame["requested_title"], strict=True))
