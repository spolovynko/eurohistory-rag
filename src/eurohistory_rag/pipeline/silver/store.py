"""The Silver table: its schema, and how a batch of rows becomes a file.

One row is one section of one article. Article-level fields -- title, themes,
categories, infobox -- are repeated on every section of that article, which is
what makes the table flat enough to read. See D-030.

Silver is a cache. It is written whole and overwritten whole; there is no
append and no partitioning, because a rebuild from Bronze takes about a minute
and nothing downstream depends on a previous run.
"""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import polars as pl
from polars.datatypes import DataType, DataTypeClass

_COLUMNS: dict[str, DataType | DataTypeClass] = {
    "doc_id": pl.Utf8,  # "30030:1" -- page_id and position
    "page_id": pl.Int64,  # key, with position
    "position": pl.UInt32,  # 0 is the lead section
    "title": pl.Utf8,
    "heading": pl.Utf8,  # "" for the lead, never null
    "text": pl.Utf8,  # the prose; this is what gets embedded
    "themes": pl.List(pl.Utf8),  # a list: one article can arrive by 3 routes
    "link_targets": pl.List(pl.Utf8),  # section-level, never embedded
    "categories": pl.List(pl.Utf8),  # article-level
    "infobox_type": pl.Utf8,  # null for the 23% with no box
    "infobox": pl.List(pl.Struct({"key": pl.Utf8, "value": pl.Utf8})),
    "revision_id": pl.Int64,  # which version this text came from
    "revision_timestamp": pl.Datetime("us", "UTC"),
    "license": pl.Utf8,  # CC BY-SA travels with the text
}

SILVER_SCHEMA = pl.Schema(_COLUMNS)


@dataclass(frozen=True, slots=True)
class SilverRow:
    """One Silver row, before it becomes a frame.

    The field list is the schema above, in Python types. Keeping both is a
    duplication, and a deliberate one: the dataclass is what mypy checks the
    transform against, the schema is what Parquet enforces on disk. Bronze
    makes the same trade with `Revision`.
    """

    doc_id: str
    page_id: int
    position: int
    title: str
    heading: str
    text: str
    themes: tuple[str, ...]
    link_targets: tuple[str, ...]
    categories: tuple[str, ...]
    infobox_type: str | None
    infobox: tuple[tuple[str, str], ...]
    revision_id: int
    revision_timestamp: dt.datetime
    license: str


def to_frame(rows: Sequence[SilverRow]) -> pl.DataFrame:
    """Build the Silver frame from rows, with the schema enforced."""
    return pl.DataFrame(
        [
            {
                "doc_id": row.doc_id,
                "page_id": row.page_id,
                "position": row.position,
                "title": row.title,
                "heading": row.heading,
                "text": row.text,
                "themes": list(row.themes),
                "link_targets": list(row.link_targets),
                "categories": list(row.categories),
                "infobox_type": row.infobox_type,
                "infobox": [{"key": k, "value": v} for k, v in row.infobox],
                "revision_id": row.revision_id,
                "revision_timestamp": row.revision_timestamp,
                "license": row.license,
            }
            for row in rows
        ],
        schema=SILVER_SCHEMA,
    )


def write(root: Path, frame: pl.DataFrame) -> Path:
    """Write the whole Silver table, replacing whatever was there.

    One file, not a directory of parts. Bronze splits per batch so a crash
    leaves complete files behind; Silver has nothing to protect, because a
    failed run is fixed by running it again.
    """
    root.mkdir(parents=True, exist_ok=True)
    path = root / "documents.parquet"
    frame.write_parquet(path)
    return path
