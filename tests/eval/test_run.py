"""The runner, against fakes -- no network, no key, no cost."""

from pathlib import Path
from typing import Any

from eurohistory_rag.eval.questions import Question
from eurohistory_rag.eval.record import new_run_id, read_records, write_run
from eurohistory_rag.eval.run import build_meta, markers_in, run_all, run_question
from eurohistory_rag.generation.client import Generator
from eurohistory_rag.generation.service import GenerationService
from eurohistory_rag.retrieval.search import SearchService
from eurohistory_rag.retrieval.sparse import (
    average_length,
    document_vector,
    tokenize,
)
from eurohistory_rag.retrieval.vectorstore import VectorStore
from tests.fakes import FakeEmbedder, FakeGenerator, UnavailableGenerator

QUESTION = Question(
    id="berlin-wall", kind="easy", text="Why was the wall built?", expected=("1:0",)
)

# (doc_id, text). One chunk per section, so doc_id and chunk_id move together.
CORPUS = [
    ("1:0", "berlin wall berlin wall"),
    ("2:0", "marshall plan marshall plan"),
    ("3:0", "treaty rome"),
]


def payload(doc_id: str, text: str) -> dict[str, Any]:
    """The payload shape `to_result` reads, with only doc_id and text varied."""
    page_id, _, section = doc_id.partition(":")
    return {
        "chunk_id": f"{doc_id}:0",
        "doc_id": doc_id,
        "page_id": int(page_id),
        "title": f"Article {page_id}",
        "heading": f"Section {section}",
        "text": text,
        "revision_id": 99,
    }


def services(generator: Generator) -> tuple[SearchService, GenerationService]:
    """A search and generation pair backed by an in-process Qdrant."""
    embedder = FakeEmbedder()
    store = VectorStore.in_memory("chunks", embedder.dimensions)
    store.ensure_collection(recreate=True)
    tokens = [tokenize(text) for _, text in CORPUS]
    average = average_length(tokens)
    store.upsert(
        [f"{doc_id}:0" for doc_id, _ in CORPUS],
        embedder.embed([text for _, text in CORPUS]),
        [document_vector(token_list, average) for token_list in tokens],
        [payload(doc_id, text) for doc_id, text in CORPUS],
    )
    search = SearchService(embedder, store)
    return search, GenerationService(search, generator)


def test_a_record_carries_the_question_its_key_and_what_came_back() -> None:
    search, generation = services(FakeGenerator("The wall went up in 1961 [1]."))
    record = run_question(QUESTION, search, generation, answer_k=2)

    assert record.question_id == "berlin-wall"
    assert record.expected_doc_ids == ["1:0"]
    assert record.retrieved[0].doc_id == "1:0"
    assert record.sources_sent == 2
    assert record.citations[0].number == 1


def test_only_the_chunks_the_model_saw_keep_their_text() -> None:
    """Ranks past the cut-off carry names only -- recall needs no text."""
    search, generation = services(FakeGenerator())
    record = run_question(QUESTION, search, generation, answer_k=1)

    assert record.retrieved[0].text
    assert all(item.text == "" for item in record.retrieved[1:])


def test_an_invented_marker_is_recorded_but_not_cited() -> None:
    """The gap between the two is the citation-validity measure."""
    search, generation = services(FakeGenerator("A claim [1] and another [9]."))
    record = run_question(QUESTION, search, generation, answer_k=2)

    assert record.markers_found == [1, 9]
    assert [c.number for c in record.citations] == [1]


def test_a_generation_failure_is_recorded_rather_than_raised() -> None:
    """One unreachable call must not throw away the questions already done."""
    search, generation = services(UnavailableGenerator())
    record = run_question(QUESTION, search, generation, answer_k=2)

    assert record.error == "connection refused"
    assert record.answer == ""
    assert record.retrieved


def test_run_all_returns_one_record_per_question_in_order() -> None:
    search, generation = services(FakeGenerator())
    questions = [
        QUESTION,
        Question(id="second", kind="unanswerable", text="Something else?"),
    ]
    records = run_all(questions, search, generation, answer_k=2)

    assert [r.question_id for r in records] == ["berlin-wall", "second"]


def test_markers_in_finds_every_marker_including_repeats() -> None:
    assert markers_in("a [1] b [2] c [1]") == [1, 2, 1]


def test_a_run_survives_being_written_and_read_back(tmp_path: Path) -> None:
    """The shape has to round-trip, or two runs cannot be compared."""
    search, generation = services(FakeGenerator())
    records = run_all([QUESTION], search, generation, answer_k=2)
    meta = build_meta(
        run_id=new_run_id(),
        settings_collection="chunks",
        embedding_model="fake",
        generation_model="fake",
        points=3,
        answer_k=2,
        max_per_document=2,
        overfetch=4,
    )

    directory = write_run(meta, records, tmp_path)
    assert read_records(directory) == records
