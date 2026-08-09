"""The infobox chunk: what it holds, where it is filed, and when it splits."""

import datetime as dt

from eurohistory_rag.pipeline.gold.infobox import HEADING, infobox_chunks
from eurohistory_rag.pipeline.silver.store import SilverRow


def silver_row(fields: tuple[tuple[str, str], ...]) -> SilverRow:
    """An article's lead row carrying `fields` as its infobox."""
    return SilverRow(
        doc_id="33166:0",
        page_id=33166,
        position=0,
        title="West Germany",
        heading="",
        text="West Germany was the informal name for the Federal Republic.",
        themes=("cold-war",),
        link_targets=(),
        categories=("Category:Cold War",),
        infobox_type="former country",
        infobox=fields,
        revision_id=901,
        revision_timestamp=dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
        license="CC BY-SA 4.0",
    )


def test_an_article_with_no_infobox_produces_nothing() -> None:
    """283 of 1,271 articles have no box, and they must cost no chunk."""
    assert infobox_chunks(silver_row(()), 1200) == []


def test_the_fields_are_in_the_text_in_the_editors_order() -> None:
    """The whole point: a value in the box becomes a value that can be found."""
    chunks = infobox_chunks(
        silver_row((("capital", "Bonn"), ("area_km2", "248,717"))), 1200
    )
    assert len(chunks) == 1
    assert chunks[0].text == (
        "West Germany -- Infobox\n\ncapital: Bonn\narea_km2: 248,717"
    )


def test_it_is_filed_under_the_articles_lead_section() -> None:
    """`doc_id` is the lead, so ground truth written against a section still works.

    `chunk_id` is its own shape, so it can never collide with a prose chunk and
    so `index --resume` can tell the new points from the paid-for ones.
    """
    chunk = infobox_chunks(silver_row((("capital", "Bonn"),)), 1200)[0]
    assert chunk.doc_id == "33166:0"
    assert chunk.chunk_id == "33166:infobox:0"
    assert chunk.heading == HEADING


def test_it_carries_no_period() -> None:
    """A box is not about a span of years, so the temporal arm must not see it."""
    chunk = infobox_chunks(silver_row((("date_signed", "28 June 1919"),)), 1200)[0]
    assert chunk.year_start is None
    assert chunk.year_end is None
    assert chunk.year_source == ""


def test_a_long_box_splits_at_field_boundaries_rather_than_losing_fields() -> None:
    """361 of the 988 boxes in this corpus exceed one chunk.

    Truncating would drop facts, which is the defect this module repairs, so the
    box is split instead -- and no field may be cut in half by the split.
    """
    fields = tuple((f"key{i}", "value " * 10) for i in range(20))
    chunks = infobox_chunks(silver_row(fields), 200)

    assert len(chunks) > 1
    assert [c.position for c in chunks] == list(range(len(chunks)))
    assert [c.chunk_id for c in chunks] == [
        f"33166:infobox:{i}" for i in range(len(chunks))
    ]
    rendered = "\n".join(line for c in chunks for line in c.text.splitlines()[2:])
    for key, value in fields:
        assert f"{key}: {value}" in rendered


def test_a_single_field_longer_than_the_budget_is_kept_whole() -> None:
    """A casualty field runs to thousands of characters and is still one fact."""
    chunks = infobox_chunks(silver_row((("casualties1", "x" * 3000),)), 1200)
    assert len(chunks) == 1
    assert "x" * 3000 in chunks[0].text
