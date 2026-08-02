"""The Gold table: its schema, and how a batch of chunks becomes a file.

One row is one chunk -- the unit that gets embedded in Phase 5, matched by
retrieval, and quoted in an answer. Everything here is derivable from Silver,
so Gold is a cache: written whole, overwritten whole, safe to delete.

The column list is deliberately narrow. A chunk carries what a citation needs
and what a filter might need, and nothing else. Silver's `categories`,
`infobox` and `link_targets` are left behind because they are article-level:
carrying them would repeat one article's metadata across all fifty of its
chunks. Adding a column back costs one rebuild. See D-0xx.
"""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import polars as pl
from polars.datatypes import DataType, DataTypeClass

_COLUMNS: dict[str, DataType | DataTypeClass] = {
    "chunk_id": pl.Utf8,  # "30030:1:4" -- doc_id and position
    "doc_id": pl.Utf8,  # the Silver row this was cut from
    "page_id": pl.Int64,  # the article, for grouping and dedup
    "position": pl.UInt32,  # 0 is the first chunk of the document
    "title": pl.Utf8,  # for the citation; also inside `text`
    "heading": pl.Utf8,  # "" for the lead, never null
    "text": pl.Utf8,  # prefix + body; this is what gets embedded
    "themes": pl.List(pl.Utf8),  # a list: one article can arrive by 3 routes
    "revision_id": pl.Int64,  # which version this text came from
    "revision_timestamp": pl.Datetime("us", "UTC"),
    "license": pl.Utf8,  # CC BY-SA travels with the text
}

GOLD_SCHEMA = pl.Schema(_COLUMNS)


@dataclass(frozen=True, slots=True)
class Chunk:
    """One chunk, before it becomes a frame.

    Frozen because a chunk is a result and not a workspace: `chunk_document`
    hands them back and nothing downstream has a reason to edit one. The field
    list restates the schema above in Python types -- the same deliberate
    duplication Silver makes with `SilverRow`, for the same reason.
    """

    chunk_id: str
    doc_id: str
    page_id: int
    position: int
    title: str
    heading: str
    text: str
    themes: tuple[str, ...]
    revision_id: int
    revision_timestamp: dt.datetime
    license: str


def to_frame(chunks: Sequence[Chunk]) -> pl.DataFrame:
    """Build the Gold frame from chunks, with the schema enforced on the way in."""
    return pl.DataFrame(
        [
            {
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "page_id": chunk.page_id,
                "position": chunk.position,
                "title": chunk.title,
                "heading": chunk.heading,
                "text": chunk.text,
                "themes": list(chunk.themes),
                "revision_id": chunk.revision_id,
                "revision_timestamp": chunk.revision_timestamp,
                "license": chunk.license,
            }
            for chunk in chunks
        ],
        schema=GOLD_SCHEMA,
    )


def write(root: Path, frame: pl.DataFrame) -> Path:
    """Write the whole Gold table, replacing whatever was there.

    One file, like Silver. A failed run is fixed by running it again, so there
    is nothing a partial write needs to protect.
    """
    root.mkdir(parents=True, exist_ok=True)
    path = root / "chunks.parquet"
    frame.write_parquet(path)
    return path
