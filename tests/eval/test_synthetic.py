"""Question generation: the sampling rule, the filters, and the round trip."""

from pathlib import Path

import polars as pl
import pytest

from eurohistory_rag.eval.questions import load_questions
from eurohistory_rag.eval.synthetic import (
    SourceChunk,
    copies_source,
    generate,
    question_id,
    render,
    sample_chunks,
    to_question,
    usable,
    write,
)
from tests.fakes import ScriptedGenerator, UnavailableGenerator

LONG = (
    "The Treaty of Rome established the European Economic Community in 1957. "
    "Six states signed it and a customs union followed over the next decade. "
) * 4


def make_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    """A minimal Gold frame with only the columns sampling reads."""
    return pl.DataFrame(rows)


def chunk_row(
    page_id: int, position: int, text: str = LONG, title: str = "Treaty of Rome"
) -> dict[str, object]:
    """One Gold row."""
    return {
        "chunk_id": f"{page_id}:0:{position}",
        "doc_id": f"{page_id}:0",
        "page_id": page_id,
        "title": title,
        "heading": "Terms",
        "text": text,
    }


def test_sample_takes_at_most_one_chunk_per_article() -> None:
    frame = make_frame([chunk_row(1, i) for i in range(5)] + [chunk_row(2, 0)])
    sampled = sample_chunks(frame, count=10)
    assert sorted(c.doc_id for c in sampled) == ["1:0", "2:0"]


def test_sample_is_deterministic_for_a_seed() -> None:
    frame = make_frame([chunk_row(page, 0) for page in range(20)])
    assert [c.chunk_id for c in sample_chunks(frame, count=5, seed=7)] == [
        c.chunk_id for c in sample_chunks(frame, count=5, seed=7)
    ]


def test_sample_drops_chunks_below_the_length_floor() -> None:
    frame = make_frame([chunk_row(1, 0, text="Too short."), chunk_row(2, 0)])
    assert [c.doc_id for c in sample_chunks(frame, count=10)] == ["2:0"]


def test_sample_respects_the_count() -> None:
    frame = make_frame([chunk_row(page, 0) for page in range(30)])
    assert len(sample_chunks(frame, count=4)) == 4


def make_chunk(text: str = LONG) -> SourceChunk:
    """One sampled chunk."""
    return SourceChunk(
        chunk_id="652:0:3",
        doc_id="652:0",
        title="Treaty of Rome",
        heading="Terms",
        text=text,
    )


def test_copies_source_catches_a_lifted_sentence() -> None:
    assert copies_source(
        "The Treaty of Rome established the European Economic Community in 1957?",
        LONG,
    )


def test_copies_source_allows_a_rewording() -> None:
    assert not copies_source(
        "Which six countries founded the EEC, and in what year?", LONG
    )


@pytest.mark.parametrize(
    "question",
    [
        "What did the Treaty of Rome establish",  # no question mark
        "Why?",  # too short
        "What does the passage say about the Treaty of Rome and its signatories?",
        "The Treaty of Rome established the European Economic Community in 1957?",
    ],
)
def test_usable_rejects(question: str) -> None:
    assert not usable(question, make_chunk())


def test_usable_accepts_a_real_question() -> None:
    assert usable("Which body did the Treaty of Rome create in 1957?", make_chunk())


def test_question_id_names_its_chunk() -> None:
    assert question_id(make_chunk()) == "syn-652-0-3"


def test_to_question_uses_the_chunk_section_as_ground_truth() -> None:
    question = to_question("Which body did the Treaty of Rome create?", make_chunk())
    assert question.expected == ("652:0",)
    assert question.kind == "synthetic"
    assert "652:0:3" in question.note


def test_generate_sorts_replies_into_accepted_skipped_and_rejected() -> None:
    chunks = [make_chunk(), make_chunk(), make_chunk()]
    generator = ScriptedGenerator(
        [
            "Which body did the Treaty of Rome create in 1957?",
            "SKIP",
            "what does this article say?",
        ]
    )
    report = generate(chunks, generator)

    assert len(report.questions) == 1
    assert (report.skipped, report.rejected, report.failed) == (1, 1, 0)


def test_generate_records_a_model_failure_and_keeps_going() -> None:
    report = generate([make_chunk(), make_chunk()], UnavailableGenerator())
    assert (len(report.questions), report.failed) == (0, 2)


def test_write_round_trips_through_the_validator(tmp_path: Path) -> None:
    """The written file must load as questions, quotes and all.

    A quoting mistake in the TOML writer would surface as an unexplained recall
    drop halfway through a paid run rather than here.
    """
    awkward = SourceChunk(
        chunk_id="1:0:0",
        doc_id="1:0",
        title='The "Iron Curtain" speech',
        heading="Reception",
        text=LONG,
    )
    question = to_question('What did Churchill mean by the "iron curtain"?', awkward)
    path = write(tmp_path / "synthetic.toml", [question], model="fake")

    loaded = load_questions(path)
    assert loaded[0].text == question.text
    assert loaded[0].expected == ("1:0",)


def test_render_warns_that_the_set_is_not_the_golden_one() -> None:
    text = render([to_question("What did the treaty create?", make_chunk())], "fake")
    assert "NOT the golden set" in text
