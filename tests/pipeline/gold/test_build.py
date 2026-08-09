"""The Silver-to-Gold build. The chunking rules are tested in `test_chunk.py`;
what is tested here is the sequence around them -- read, convert, write.
"""

import datetime as dt
from pathlib import Path

import polars as pl

from eurohistory_rag.pipeline.gold.build import build, read_documents, to_document
from eurohistory_rag.pipeline.gold.store import GOLD_SCHEMA
from eurohistory_rag.pipeline.silver.store import SilverRow
from eurohistory_rag.pipeline.silver.store import to_frame as silver_frame
from eurohistory_rag.pipeline.silver.store import write as silver_write

# --- helpers ----------------------------------------------------------------


def silver_row(page_id: int, position: int, text: str) -> SilverRow:
    """A Silver row with every field populated, so `to_document` is exercised."""
    return SilverRow(
        doc_id=f"{page_id}:{position}",
        page_id=page_id,
        position=position,
        title=f"Article {page_id}",
        heading="" if position == 0 else f"Section {position}",
        text=text,
        themes=("cold-war",),
        link_targets=("Harry S. Truman",),
        categories=("Category:Cold War",),
        infobox_type="settlement",
        infobox=(("capital", "Paris"), ("founded", "1957")),
        revision_id=100 + page_id,
        revision_timestamp=dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
        license="CC BY-SA 4.0",
    )


def write_silver(root: Path, rows: list[SilverRow]) -> None:
    """Put a Silver table on disk where `build` will look for it."""
    silver_write(root, silver_frame(rows))


def long_text(marker: str, sentences: int) -> str:
    """Enough prose to force several chunks at production size."""
    return " ".join(
        f"{marker} sentence {i} records a decision." for i in range(sentences)
    )


# --- reading ----------------------------------------------------------------


def test_documents_are_read_in_page_and_position_order(tmp_path: Path) -> None:
    write_silver(
        tmp_path,
        [
            silver_row(20, 1, "Later article, second section."),
            silver_row(10, 1, "Earlier article, second section."),
            silver_row(20, 0, "Later article, lead."),
            silver_row(10, 0, "Earlier article, lead."),
        ],
    )
    documents = read_documents(tmp_path)
    assert documents.select("page_id", "position").rows() == [
        (10, 0),
        (10, 1),
        (20, 0),
        (20, 1),
    ]


def test_a_parquet_row_converts_back_to_the_silver_row_it_came_from(
    tmp_path: Path,
) -> None:
    original = silver_row(30030, 1, "A short section.")
    write_silver(tmp_path, [original])
    row = read_documents(tmp_path).row(0, named=True)
    assert to_document(row) == original


# --- building ---------------------------------------------------------------


def test_gold_is_written_with_its_schema(tmp_path: Path) -> None:
    write_silver(tmp_path / "silver", [silver_row(1, 0, "A short section.")])
    report = build(tmp_path / "silver", tmp_path / "gold", 1200, 150)
    assert report.path == tmp_path / "gold" / "chunks.parquet"
    assert pl.read_parquet(report.path).schema == GOLD_SCHEMA


def test_the_report_counts_documents_and_chunks(tmp_path: Path) -> None:
    write_silver(
        tmp_path / "silver",
        [
            silver_row(1, 0, "A short section."),
            silver_row(2, 0, long_text("Alpha", 120)),
        ],
    )
    report = build(tmp_path / "silver", tmp_path / "gold", 1200, 0)
    assert report.documents == 2
    assert report.chunks == pl.read_parquet(report.path).height
    assert report.chunks > 2


def test_a_smaller_size_produces_more_chunks(tmp_path: Path) -> None:
    write_silver(tmp_path / "silver", [silver_row(1, 1, long_text("Alpha", 120))])
    large = build(tmp_path / "silver", tmp_path / "gold", 1200, 0)
    small = build(tmp_path / "silver", tmp_path / "gold", 400, 0)
    assert small.chunks > large.chunks


def test_a_rebuild_replaces_rather_than_appends(tmp_path: Path) -> None:
    write_silver(tmp_path / "silver", [silver_row(1, 0, "A short section.")])
    first = build(tmp_path / "silver", tmp_path / "gold", 1200, 150)
    second = build(tmp_path / "silver", tmp_path / "gold", 1200, 150)
    assert first.chunks == second.chunks
    assert pl.read_parquet(second.path).height == second.chunks


def test_provenance_survives_the_round_trip(tmp_path: Path) -> None:
    write_silver(tmp_path / "silver", [silver_row(30030, 2, "A short section.")])
    report = build(tmp_path / "silver", tmp_path / "gold", 1200, 150)
    chunk = pl.read_parquet(report.path).row(0, named=True)
    assert chunk["chunk_id"] == "30030:2:0"
    assert chunk["doc_id"] == "30030:2"
    assert chunk["title"] == "Article 30030"
    assert chunk["heading"] == "Section 2"
    assert chunk["themes"] == ["cold-war"]
    assert chunk["revision_id"] == 30130
    assert chunk["license"] == "CC BY-SA 4.0"
    assert chunk["text"] == "Article 30030 — Section 2\n\nA short section."


def test_the_infobox_arrives_once_per_article_after_every_prose_chunk(
    tmp_path: Path,
) -> None:
    """Once per article, not once per section, and at the end of the table.

    Both halves are load-bearing. Silver repeats the box on every section row,
    so a naive loop would write it fifty times; and appending at the end is what
    leaves the existing chunk ids and their order untouched, which is what lets
    `index --resume` skip the corpus it has already paid to embed. D-097.
    """
    silver = tmp_path / "silver"
    gold = tmp_path / "gold"
    write_silver(
        silver,
        [
            silver_row(1, 0, long_text("alpha", 40)),
            silver_row(1, 1, long_text("beta", 40)),
            silver_row(2, 0, long_text("gamma", 40)),
        ],
    )

    build(silver, gold, size=1200, overlap=150)
    frame = pl.read_parquet(gold / "chunks.parquet")
    is_infobox = frame["chunk_id"].str.contains(":infobox:")

    assert frame.filter(is_infobox)["chunk_id"].to_list() == [
        "1:infobox:0",
        "2:infobox:0",
    ]
    prose = frame.slice(0, int((~is_infobox).sum()))
    assert not prose["chunk_id"].str.contains(":infobox:").any()
    assert frame.filter(is_infobox)["doc_id"].to_list() == ["1:0", "2:0"]
