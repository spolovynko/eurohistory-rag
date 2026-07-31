"""The Bronze layer: schema, partition layout, and the resume key set."""

import datetime as dt
from pathlib import Path

import polars as pl

from eurohistory_rag.data_ingestion.bronze import (
    BRONZE_SCHEMA,
    LICENSE,
    ingested_keys,
    partition_path,
    to_frame,
    write_batch,
)
from eurohistory_rag.data_ingestion.wikipedia import Revision

FETCHED_AT = dt.datetime(2026, 7, 31, 9, 59, 31, tzinfo=dt.UTC)


def revision(page_id: int = 1, title: str = "Stalinism", **kwargs: object) -> Revision:
    defaults: dict[str, object] = {
        "page_id": page_id,
        "title": title,
        "requested_title": title,
        "revision_id": page_id * 10,
        "revision_timestamp": dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.UTC),
        "wikitext": "{{Infobox}}",
    }
    return Revision(**{**defaults, **kwargs})  # type: ignore[arg-type]


# --- to_frame --------------------------------------------------------------


def test_the_frame_matches_the_declared_schema() -> None:
    """Dtypes are declared, not inferred, so an empty batch types the same."""
    frame = to_frame([revision()], "interwar", FETCHED_AT)

    assert frame.schema == BRONZE_SCHEMA


def test_an_empty_batch_still_has_the_schema() -> None:
    frame = to_frame([], "interwar", FETCHED_AT)

    assert frame.height == 0
    assert frame.schema == BRONZE_SCHEMA


def test_provenance_is_carried_through() -> None:
    frame = to_frame(
        [revision(page_id=4764461, title="World War I", requested_title="Great War")],
        "wwi-and-aftermath",
        FETCHED_AT,
    )

    row = frame.row(0, named=True)
    assert row["page_id"] == 4764461
    assert row["title"] == "World War I"
    assert row["requested_title"] == "Great War"
    assert row["theme"] == "wwi-and-aftermath"
    assert row["revision_id"] == 47644610
    assert row["fetched_at"] == FETCHED_AT
    assert row["license"] == LICENSE


def test_fetched_at_is_uniform_across_a_batch() -> None:
    """One run, one timestamp -- so it is a parameter, not a call inside."""
    frame = to_frame([revision(1), revision(2), revision(3)], "interwar", FETCHED_AT)

    assert frame["fetched_at"].unique().to_list() == [FETCHED_AT]


def test_revision_timestamp_and_fetched_at_are_different_questions() -> None:
    """How old the article is, versus how stale our copy is."""
    frame = to_frame([revision()], "interwar", FETCHED_AT)

    row = frame.row(0, named=True)
    assert row["revision_timestamp"] != row["fetched_at"]


# --- partitioning and writing ----------------------------------------------


def test_the_partition_is_one_directory_per_ingest_day(tmp_path: Path) -> None:
    assert partition_path(tmp_path, FETCHED_AT).name == "ingest_date=2026-07-31"


def test_write_batch_creates_the_partition_directory(tmp_path: Path) -> None:
    path = write_batch(
        tmp_path, to_frame([revision()], "interwar", FETCHED_AT), FETCHED_AT
    )

    assert path.parent == tmp_path / "ingest_date=2026-07-31"
    assert path.suffix == ".parquet"
    assert pl.read_parquet(path).height == 1


def test_each_batch_gets_its_own_file(tmp_path: Path) -> None:
    """Append-only in practice: nothing already written is ever reopened."""
    first = write_batch(
        tmp_path, to_frame([revision(1)], "interwar", FETCHED_AT), FETCHED_AT
    )
    second = write_batch(
        tmp_path, to_frame([revision(2)], "interwar", FETCHED_AT), FETCHED_AT
    )

    assert first != second
    assert len(list(tmp_path.rglob("*.parquet"))) == 2
    assert pl.read_parquet(tmp_path / "**" / "*.parquet").height == 2


def test_a_written_frame_reads_back_identically(tmp_path: Path) -> None:
    frame = to_frame([revision()], "interwar", FETCHED_AT)

    path = write_batch(tmp_path, frame, FETCHED_AT)

    assert pl.read_parquet(path).equals(frame)


# --- ingested_keys ---------------------------------------------------------


def test_no_bronze_directory_gives_no_keys(tmp_path: Path) -> None:
    assert ingested_keys(tmp_path / "does-not-exist") == set()


def test_an_empty_bronze_directory_gives_no_keys(tmp_path: Path) -> None:
    assert ingested_keys(tmp_path) == set()


def test_keys_are_theme_and_requested_title(tmp_path: Path) -> None:
    """Keyed on what the registry asked for, since that is what resume compares."""
    frame = to_frame(
        [revision(title="World War I", requested_title="Great War")],
        "wwi-and-aftermath",
        FETCHED_AT,
    )
    write_batch(tmp_path, frame, FETCHED_AT)

    assert ingested_keys(tmp_path) == {("wwi-and-aftermath", "Great War")}


def test_keys_span_every_file_and_partition(tmp_path: Path) -> None:
    later = FETCHED_AT + dt.timedelta(days=1)
    write_batch(
        tmp_path, to_frame([revision(1, "A")], "interwar", FETCHED_AT), FETCHED_AT
    )
    write_batch(tmp_path, to_frame([revision(2, "B")], "interwar", later), later)

    assert ingested_keys(tmp_path) == {("interwar", "A"), ("interwar", "B")}


def test_the_same_title_under_two_themes_is_two_keys(tmp_path: Path) -> None:
    """Adolf Hitler belongs to interwar and to wwii; both must be tracked."""
    for theme in ("interwar", "wwii-and-holocaust"):
        frame = to_frame([revision(title="Adolf Hitler")], theme, FETCHED_AT)
        write_batch(tmp_path, frame, FETCHED_AT)

    assert ingested_keys(tmp_path) == {
        ("interwar", "Adolf Hitler"),
        ("wwii-and-holocaust", "Adolf Hitler"),
    }
