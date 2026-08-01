"""The Silver table: schema, the write, and the Bronze-to-Silver build."""

import datetime as dt
from pathlib import Path

import polars as pl

from eurohistory_rag.pipeline.bronze.store import BRONZE_SCHEMA, LICENSE
from eurohistory_rag.pipeline.silver.build import article_rows, build, read_articles
from eurohistory_rag.pipeline.silver.store import (
    SILVER_SCHEMA,
    SilverRow,
    to_frame,
    write,
)

TIMESTAMP = dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.UTC)
LONG = "Prose about the subject, long enough to clear the minimum. " * 6


def wikitext(*, infobox: bool = True, categories: bool = True) -> str:
    parts = []
    if infobox:
        parts.append("{{Infobox treaty\n| date_signed = 28 June 1919\n}}")
    parts.append(f"[[Weimar Republic|the republic]] {LONG}")
    parts.append(f"== Background ==\n[[Berlin]] {LONG}")
    parts.append("== References ==\nSee below.")
    if categories:
        parts.append("[[Category:Treaties]]")
    return "\n\n".join(parts)


def bronze_row(
    page_id: int = 30030, theme: str = "interwar", **kwargs: object
) -> dict[str, object]:
    row: dict[str, object] = {
        "page_id": page_id,
        "title": "Treaty of Versailles",
        "requested_title": "Treaty of Versailles",
        "theme": theme,
        "revision_id": 900,
        "revision_timestamp": TIMESTAMP,
        "wikitext": wikitext(),
        "fetched_at": TIMESTAMP,
        "license": LICENSE,
    }
    return {**row, **kwargs}


def write_bronze(root: Path, rows: list[dict[str, object]]) -> None:
    directory = root / "ingest_date=2026-07-31"
    directory.mkdir(parents=True)
    pl.DataFrame(rows, schema=BRONZE_SCHEMA).write_parquet(directory / "part-a.parquet")


def row(**kwargs: object) -> SilverRow:
    defaults: dict[str, object] = {
        "doc_id": "30030:0",
        "page_id": 30030,
        "position": 0,
        "title": "Treaty of Versailles",
        "heading": "",
        "text": "Prose.",
        "themes": ("interwar",),
        "link_targets": ("Berlin",),
        "categories": ("Treaties",),
        "infobox_type": "treaty",
        "infobox": (("date_signed", "28 June 1919"),),
        "revision_id": 900,
        "revision_timestamp": TIMESTAMP,
        "license": LICENSE,
    }
    return SilverRow(**{**defaults, **kwargs})  # type: ignore[arg-type]


# --- the schema ------------------------------------------------------------


def test_the_frame_matches_the_declared_schema() -> None:
    """Dtypes are declared, not inferred, so an empty build types the same."""
    assert to_frame([row()]).schema == SILVER_SCHEMA


def test_an_empty_build_still_has_the_schema() -> None:
    assert to_frame([]).schema == SILVER_SCHEMA


def test_infobox_type_is_null_when_there_is_no_box() -> None:
    """The 23% with no infobox; an empty field list would not say the same thing."""
    frame = to_frame([row(infobox_type=None, infobox=())])

    assert frame["infobox_type"][0] is None
    assert frame["infobox"][0].to_list() == []


def test_the_infobox_survives_a_parquet_round_trip(tmp_path: Path) -> None:
    """A struct list is the part of the schema most likely to break on disk."""
    path = write(tmp_path, to_frame([row()]))
    back = pl.read_parquet(path)

    assert back.schema == SILVER_SCHEMA
    assert back["infobox"][0].to_list() == [
        {"key": "date_signed", "value": "28 June 1919"}
    ]


def test_writing_twice_replaces_rather_than_appends(tmp_path: Path) -> None:
    """Silver is a cache: a rebuild overwrites, unlike append-only Bronze."""
    write(tmp_path, to_frame([row(), row(position=1, doc_id="30030:1")]))
    path = write(tmp_path, to_frame([row()]))

    assert pl.read_parquet(path).height == 1


# --- reading bronze --------------------------------------------------------


def test_an_article_in_two_themes_becomes_one_row_with_both(tmp_path: Path) -> None:
    """Otherwise the same text is embedded twice and eats two slots in one top-k."""
    write_bronze(tmp_path, [bronze_row(theme="interwar"), bronze_row(theme="wwii")])

    articles = read_articles(tmp_path)

    assert articles.height == 1
    assert articles["themes"][0].to_list() == ["interwar", "wwii"]


def test_distinct_articles_are_kept_apart(tmp_path: Path) -> None:
    write_bronze(tmp_path, [bronze_row(page_id=1), bronze_row(page_id=2)])

    assert read_articles(tmp_path).height == 2


# --- one article to rows ---------------------------------------------------


def test_article_level_fields_are_copied_onto_every_section() -> None:
    rows = article_rows(
        page_id=30030,
        title="Treaty of Versailles",
        wikitext=wikitext(),
        themes=["interwar"],
        revision_id=900,
        revision_timestamp=TIMESTAMP,
        license=LICENSE,
    )

    assert len(rows) == 2
    assert {r.infobox_type for r in rows} == {"treaty"}
    assert {r.categories for r in rows} == {("Treaties",)}


def test_doc_id_is_the_page_and_the_position() -> None:
    rows = article_rows(
        page_id=30030,
        title="Treaty of Versailles",
        wikitext=wikitext(),
        themes=["interwar"],
        revision_id=900,
        revision_timestamp=TIMESTAMP,
        license=LICENSE,
    )

    assert [r.doc_id for r in rows] == ["30030:0", "30030:1"]


def test_an_article_without_an_infobox_gives_null_rows() -> None:
    rows = article_rows(
        page_id=1,
        title="Diktat",
        wikitext=wikitext(infobox=False),
        themes=["interwar"],
        revision_id=1,
        revision_timestamp=TIMESTAMP,
        license=LICENSE,
    )

    assert all(r.infobox_type is None and r.infobox == () for r in rows)


# --- the whole build -------------------------------------------------------


def test_build_writes_one_row_per_surviving_section(tmp_path: Path) -> None:
    write_bronze(tmp_path / "bronze", [bronze_row()])

    report = build(tmp_path / "bronze", tmp_path / "silver")

    assert report.articles == 1
    assert report.skipped == 0
    assert report.rows == 2
    assert pl.read_parquet(report.path).schema == SILVER_SCHEMA


def test_build_skips_non_content_articles(tmp_path: Path) -> None:
    write_bronze(
        tmp_path / "bronze",
        [bronze_row(page_id=1, title="List of treaties"), bronze_row(page_id=2)],
    )

    report = build(tmp_path / "bronze", tmp_path / "silver")

    assert report.skipped == 1
    assert report.rows == 2


def test_build_is_repeatable(tmp_path: Path) -> None:
    """It is a cache rebuild, so running it twice must give the same table."""
    write_bronze(tmp_path / "bronze", [bronze_row()])

    first = pl.read_parquet(build(tmp_path / "bronze", tmp_path / "silver").path)
    second = pl.read_parquet(build(tmp_path / "bronze", tmp_path / "silver").path)

    assert first.equals(second)
