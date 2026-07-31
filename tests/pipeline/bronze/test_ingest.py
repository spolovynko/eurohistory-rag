"""The ingest loop: batching, resume, and what the report says.

Driven by a fake RevisionSource that records the batches it was asked for, so
the batching and skip logic are observable without a network or a real client.
"""

import datetime as dt
import logging
from collections.abc import Sequence
from pathlib import Path

import polars as pl
import pytest

from eurohistory_rag.pipeline.bronze.ingest import ingest
from eurohistory_rag.pipeline.bronze.registry import RegistryEntry
from eurohistory_rag.pipeline.bronze.store import ingested_keys
from eurohistory_rag.pipeline.bronze.wikipedia import (
    MAX_TITLES_PER_REQUEST,
    FetchResult,
    Revision,
)

FETCHED_AT = dt.datetime(2026, 7, 31, 9, 59, 31, tzinfo=dt.UTC)


class RecordingSource:
    """Returns a revision for every title asked for, and remembers the batches."""

    def __init__(self, missing: frozenset[str] = frozenset()) -> None:
        self.batches: list[tuple[str, ...]] = []
        self._missing = missing

    def fetch_batch(self, titles: Sequence[str]) -> FetchResult:
        self.batches.append(tuple(titles))
        revisions = tuple(
            Revision(
                page_id=abs(hash(t)) % 10**6,
                title=t,
                requested_title=t,
                revision_id=1,
                revision_timestamp=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
                wikitext=f"wikitext for {t}",
            )
            for t in titles
            if t not in self._missing
        )
        return FetchResult(
            revisions=revisions,
            missing=tuple(t for t in titles if t in self._missing),
        )


def entries(theme: str, *titles: str) -> list[RegistryEntry]:
    return [RegistryEntry(theme=theme, title=t, seed_count=2) for t in titles]


# --- the happy path --------------------------------------------------------


def test_every_entry_is_fetched_and_written(tmp_path: Path) -> None:
    source = RecordingSource()

    report = ingest(
        source, entries("interwar", "A", "B"), tmp_path, fetched_at=FETCHED_AT
    )

    assert report.written == 2
    assert report.skipped == 0
    assert report.missing == ()
    assert pl.read_parquet(tmp_path / "**" / "*.parquet").height == 2


def test_nothing_to_do_writes_no_files(tmp_path: Path) -> None:
    report = ingest(RecordingSource(), [], tmp_path, fetched_at=FETCHED_AT)

    assert report == report.__class__(requested=0, skipped=0, written=0, missing=())
    assert list(tmp_path.rglob("*.parquet")) == []


# --- batching --------------------------------------------------------------


def test_titles_are_split_into_batches(tmp_path: Path) -> None:
    source = RecordingSource()

    ingest(
        source,
        entries("interwar", "A", "B", "C", "D", "E"),
        tmp_path,
        fetched_at=FETCHED_AT,
        batch_size=2,
    )

    assert source.batches == [("A", "B"), ("C", "D"), ("E",)]


def test_a_batch_never_mixes_themes(tmp_path: Path) -> None:
    """A Bronze row carries one theme, so a mixed batch could not be written."""
    source = RecordingSource()
    mixed = entries("interwar", "A") + entries("wwii-and-holocaust", "B")

    ingest(source, mixed, tmp_path, fetched_at=FETCHED_AT, batch_size=50)

    assert source.batches == [("A",), ("B",)]


@pytest.mark.parametrize("size", [0, -1, MAX_TITLES_PER_REQUEST + 1])
def test_an_impossible_batch_size_is_rejected(tmp_path: Path, size: int) -> None:
    with pytest.raises(ValueError, match="batch_size"):
        ingest(
            RecordingSource(),
            entries("interwar", "A"),
            tmp_path,
            fetched_at=FETCHED_AT,
            batch_size=size,
        )


# --- idempotency and resume ------------------------------------------------


def test_a_second_run_fetches_nothing(tmp_path: Path) -> None:
    rows = entries("interwar", "A", "B")
    ingest(RecordingSource(), rows, tmp_path, fetched_at=FETCHED_AT)

    source = RecordingSource()
    report = ingest(source, rows, tmp_path, fetched_at=FETCHED_AT)

    assert source.batches == []
    assert (report.written, report.skipped) == (0, 2)


def test_a_resume_fetches_only_what_is_missing(tmp_path: Path) -> None:
    """The crash-at-article-600 case: the second run picks up where it stopped."""
    ingest(
        RecordingSource(),
        entries("interwar", "A", "B"),
        tmp_path,
        fetched_at=FETCHED_AT,
    )

    source = RecordingSource()
    report = ingest(
        source, entries("interwar", "A", "B", "C"), tmp_path, fetched_at=FETCHED_AT
    )

    assert source.batches == [("C",)]
    assert (report.written, report.skipped) == (1, 2)


def test_refresh_ignores_what_is_already_stored(tmp_path: Path) -> None:
    rows = entries("interwar", "A", "B")
    ingest(RecordingSource(), rows, tmp_path, fetched_at=FETCHED_AT)

    source = RecordingSource()
    report = ingest(source, rows, tmp_path, fetched_at=FETCHED_AT, refresh=True)

    assert source.batches == [("A", "B")]
    assert (report.written, report.skipped) == (2, 0)


def test_the_same_title_in_two_themes_is_fetched_for_each(tmp_path: Path) -> None:
    """Adolf Hitler belongs to both themes, so Bronze holds a row for each."""
    rows = entries("interwar", "Adolf Hitler") + entries(
        "wwii-and-holocaust", "Adolf Hitler"
    )
    source = RecordingSource()

    report = ingest(source, rows, tmp_path, fetched_at=FETCHED_AT)

    assert report.written == 2
    assert ingested_keys(tmp_path) == {
        ("interwar", "Adolf Hitler"),
        ("wwii-and-holocaust", "Adolf Hitler"),
    }


# --- missing entries -------------------------------------------------------


def test_missing_titles_are_reported_and_not_written(tmp_path: Path) -> None:
    source = RecordingSource(missing=frozenset({"Deleted"}))

    report = ingest(
        source, entries("interwar", "A", "Deleted"), tmp_path, fetched_at=FETCHED_AT
    )

    assert report.missing == ("Deleted",)
    assert report.written == 1


def test_a_missing_title_is_retried_on_the_next_run(tmp_path: Path) -> None:
    """It never reached Bronze, so the skip set does not cover it."""
    rows = entries("interwar", "Deleted")
    ingest(
        RecordingSource(missing=frozenset({"Deleted"})),
        rows,
        tmp_path,
        fetched_at=FETCHED_AT,
    )

    source = RecordingSource(missing=frozenset({"Deleted"}))
    ingest(source, rows, tmp_path, fetched_at=FETCHED_AT)

    assert source.batches == [("Deleted",)]


def test_a_batch_of_only_missing_titles_writes_no_file(tmp_path: Path) -> None:
    source = RecordingSource(missing=frozenset({"Deleted"}))

    ingest(source, entries("interwar", "Deleted"), tmp_path, fetched_at=FETCHED_AT)

    assert list(tmp_path.rglob("*.parquet")) == []


# --- logging ---------------------------------------------------------------


def test_progress_is_logged_not_printed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The core stays silent by default; the CLI decides what is shown."""
    with caplog.at_level(logging.INFO, logger="eurohistory_rag.pipeline.bronze.ingest"):
        ingest(
            RecordingSource(), entries("interwar", "A"), tmp_path, fetched_at=FETCHED_AT
        )

    assert any("interwar" in r.getMessage() for r in caplog.records)
