"""Chunking is pure logic with no I/O, so it is the one thing here that can be
tested exhaustively. Each test names a decision from `decisions.md` and pins it.
"""

import datetime as dt

import pytest

from eurohistory_rag.pipeline.gold.chunk import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    chunk_document,
    split_sentences,
)
from eurohistory_rag.pipeline.silver.store import SilverRow

# --- helpers ----------------------------------------------------------------


def make_doc(
    text: str, *, title: str = "Marshall Plan", heading: str = "Origins"
) -> SilverRow:
    """A Silver row carrying `text`. Every other field is a fixed stand-in."""
    return SilverRow(
        doc_id="30030:1",
        page_id=30030,
        position=1,
        title=title,
        heading=heading,
        text=text,
        themes=("cold-war", "integration"),
        link_targets=("Harry S. Truman",),
        categories=("Category:Cold War",),
        infobox_type=None,
        infobox=(),
        revision_id=987654,
        revision_timestamp=dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
        license="CC BY-SA 4.0",
    )


def paragraph_of(chars: int, marker: str = "x") -> str:
    """A paragraph of exactly `chars` characters, ending in a full stop.

    Lets the packing tests do exact arithmetic against `size`.
    """
    filler = (marker + " ") * chars
    return filler[: chars - 1].rstrip().ljust(chars - 1, marker) + "."


def sentences_of(marker: str, count: int) -> str:
    """A paragraph of `count` short, individually identifiable sentences.

    The overlap tests need to point at one sentence and say "that one came
    across", which `paragraph_of` cannot express.
    """
    return " ".join(f"{marker} sentence {i} records a decision." for i in range(count))


def body_of(chunk_text: str) -> str:
    """The chunk text with its `"{title} -- {heading}"` prefix removed."""
    return chunk_text.split("\n\n", 1)[1]


# --- split_sentences --------------------------------------------------------


def test_splits_on_a_full_stop_before_a_capital() -> None:
    text = "The conference collapsed in June. Molotov walked out that evening."
    assert split_sentences(text) == [
        "The conference collapsed in June.",
        "Molotov walked out that evening.",
    ]


def test_does_not_split_inside_a_known_abbreviation() -> None:
    text = "The U.S. Congress approved the funds. Europe received them in April."
    assert split_sentences(text) == [
        "The U.S. Congress approved the funds.",
        "Europe received them in April.",
    ]


def test_a_single_sentence_stays_whole() -> None:
    assert split_sentences("One sentence only.") == ["One sentence only."]


def test_blank_text_has_no_sentences() -> None:
    assert split_sentences("   \n\n  ") == []


# --- the text of a chunk (D: title and heading prefix) ----------------------


def test_prefix_carries_title_and_heading() -> None:
    chunks = chunk_document(make_doc("A short section."), CHUNK_SIZE, CHUNK_OVERLAP)
    assert chunks[0].text == "Marshall Plan — Origins\n\nA short section."


def test_lead_section_prefix_is_the_title_alone() -> None:
    doc = make_doc("A short section.", heading="")
    chunks = chunk_document(doc, CHUNK_SIZE, CHUNK_OVERLAP)
    assert chunks[0].text == "Marshall Plan\n\nA short section."


def test_prefix_does_not_count_against_the_size_budget() -> None:
    doc = make_doc(paragraph_of(CHUNK_SIZE))
    chunks = chunk_document(doc, CHUNK_SIZE, CHUNK_OVERLAP)
    assert len(chunks) == 1
    assert len(body_of(chunks[0].text)) == CHUNK_SIZE


# --- bare subheadings -------------------------------------------------------


def test_a_subheading_travels_with_the_paragraph_below_it() -> None:
    doc = make_doc(
        f"{paragraph_of(1000, 'a')}\n\nRefugee status\n\n{paragraph_of(900, 'b')}"
    )
    chunks = chunk_document(doc, 1200, 0)
    assert len(chunks) == 2
    assert not body_of(chunks[0].text).endswith("Refugee status")
    assert body_of(chunks[1].text).startswith("Refugee status\n")


def test_consecutive_subheadings_travel_together() -> None:
    headings = "Personal views\n\nPolitical views"
    doc = make_doc(
        f"{paragraph_of(1000, 'a')}\n\n{headings}\n\n{paragraph_of(900, 'b')}"
    )
    chunks = chunk_document(doc, 1200, 0)
    assert body_of(chunks[1].text).startswith("Personal views\nPolitical views\n")


def test_a_subheading_never_becomes_a_chunk_of_its_own() -> None:
    doc = make_doc(
        f"Development\n\n{paragraph_of(1195, 'a')}\n\n{paragraph_of(900, 'b')}"
    )
    chunks = chunk_document(doc, 1200, 0)
    assert all(len(body_of(chunk.text)) > 100 for chunk in chunks)


def test_a_trailing_subheading_is_kept_rather_than_dropped() -> None:
    doc = make_doc(f"{paragraph_of(600, 'a')}\n\nMajor cities and towns")
    chunks = chunk_document(doc, 1200, 0)
    assert body_of(chunks[-1].text).endswith("Major cities and towns")


def test_a_short_paragraph_that_ends_in_a_stop_is_not_a_heading() -> None:
    remark = "A short closing remark."
    doc = make_doc(f"{paragraph_of(1000, 'a')}\n\n{remark}\n\n{paragraph_of(900, 'b')}")
    chunks = chunk_document(doc, 1200, 0)
    assert body_of(chunks[0].text).endswith("A short closing remark.")


# --- the boundary ladder ----------------------------------------------------


def test_paragraphs_that_fit_are_never_cut() -> None:
    first, second = paragraph_of(700, "a"), paragraph_of(700, "b")
    chunks = chunk_document(make_doc(f"{first}\n\n{second}"), 1200, 0)
    assert [body_of(chunk.text) for chunk in chunks] == [first, second]


def test_an_oversized_paragraph_is_cut_at_sentence_ends() -> None:
    doc = make_doc(sentences_of("Alpha", 80))
    chunks = chunk_document(doc, 1200, 0)
    assert len(chunks) > 1
    assert all(chunk.text.endswith("records a decision.") for chunk in chunks)


def test_an_oversized_sentence_is_cut_at_word_boundaries() -> None:
    words = [f"w{i}" for i in range(600)]
    chunks = chunk_document(make_doc(" ".join(words)), 1200, 0)
    assert len(chunks) > 1
    recovered = [word for chunk in chunks for word in body_of(chunk.text).split()]
    assert recovered == words


def test_no_body_exceeds_the_requested_size() -> None:
    doc = make_doc("\n\n".join(sentences_of(f"P{i}", 40) for i in range(10)))
    chunks = chunk_document(doc, 1200, 0)
    assert all(len(body_of(chunk.text)) <= 1200 for chunk in chunks)


# --- overlap ----------------------------------------------------------------


def test_the_first_chunk_carries_no_overlap() -> None:
    doc = make_doc(f"{sentences_of('Alpha', 30)}\n\n{sentences_of('Beta', 30)}")
    chunks = chunk_document(doc, 1200, 150)
    assert "Beta" not in chunks[0].text
    assert body_of(chunks[0].text) == sentences_of("Alpha", 30)


def test_a_later_chunk_repeats_the_previous_tail() -> None:
    doc = make_doc(f"{sentences_of('Alpha', 30)}\n\n{sentences_of('Beta', 30)}")
    chunks = chunk_document(doc, 1200, 150)
    assert "Alpha sentence 29 records a decision." in chunks[1].text
    assert "Alpha sentence 0 records a decision." not in chunks[1].text


def test_overlap_stays_within_its_budget() -> None:
    doc = make_doc(f"{sentences_of('Alpha', 30)}\n\n{sentences_of('Beta', 30)}")
    chunks = chunk_document(doc, 1200, 150)
    carried = body_of(chunks[1].text).split("\n\n")[0]
    assert len(carried) <= 150


def test_overlap_does_not_cascade_forward() -> None:
    doc = make_doc("\n\n".join(sentences_of(m, 30) for m in ("Alpha", "Beta", "Gamma")))
    chunks = chunk_document(doc, 1200, 150)
    assert "Alpha" not in chunks[2].text


def test_zero_overlap_repeats_nothing() -> None:
    doc = make_doc(f"{sentences_of('Alpha', 30)}\n\n{sentences_of('Beta', 30)}")
    chunks = chunk_document(doc, 1200, 0)
    assert "Alpha" not in chunks[1].text


# --- edge rules -------------------------------------------------------------


def test_a_document_shorter_than_one_chunk_is_one_chunk() -> None:
    chunks = chunk_document(make_doc("Three words here."), CHUNK_SIZE, CHUNK_OVERLAP)
    assert len(chunks) == 1
    assert body_of(chunks[0].text) == "Three words here."


def test_empty_text_produces_no_chunks() -> None:
    assert chunk_document(make_doc("   \n\n   "), CHUNK_SIZE, CHUNK_OVERLAP) == []


def test_a_tiny_final_chunk_is_merged_backwards() -> None:
    tail = paragraph_of(60, "c")
    text = "\n\n".join((paragraph_of(1000, "a"), paragraph_of(1150, "b"), tail))
    chunks = chunk_document(make_doc(text), 1200, 0)
    assert len(chunks) == 2
    assert body_of(chunks[1].text).endswith(tail)


def test_a_final_chunk_above_the_floor_is_kept() -> None:
    tail = paragraph_of(250, "c")
    text = "\n\n".join((paragraph_of(1000, "a"), paragraph_of(1150, "b"), tail))
    chunks = chunk_document(make_doc(text), 1200, 0)
    assert len(chunks) == 3
    assert body_of(chunks[2].text) == tail


def test_overlap_not_smaller_than_size_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be smaller than size"):
        chunk_document(make_doc("Anything."), 100, 100)


# --- what every chunk carries -----------------------------------------------


def test_ids_and_positions_are_sequential() -> None:
    doc = make_doc("\n\n".join(paragraph_of(1000, m) for m in "abcd"))
    chunks = chunk_document(doc, 1200, 0)
    assert [chunk.position for chunk in chunks] == [0, 1, 2, 3]
    assert [chunk.chunk_id for chunk in chunks] == [
        "30030:1:0",
        "30030:1:1",
        "30030:1:2",
        "30030:1:3",
    ]


def test_provenance_is_copied_onto_every_chunk() -> None:
    doc = make_doc("\n\n".join(paragraph_of(1000, m) for m in "abc"))
    chunks = chunk_document(doc, 1200, 0)
    assert len(chunks) == 3
    for chunk in chunks:
        assert chunk.doc_id == "30030:1"
        assert chunk.page_id == 30030
        assert chunk.title == "Marshall Plan"
        assert chunk.heading == "Origins"
        assert chunk.themes == ("cold-war", "integration")
        assert chunk.revision_id == 987654
        assert chunk.license == "CC BY-SA 4.0"
