"""Tests for the answer path.

Nothing here calls a model. What is being checked is what we do with the text
a model returns -- which markers become sources, which are dropped, and what
reaches the caller -- not whether the model writes good history.
"""

import pytest

from eurohistory_rag.generation.service import Answer, GenerationService, cited
from eurohistory_rag.retrieval.search import SearchResult
from tests.fakes import FakeGenerator, UnavailableGenerator

# --- helpers ----------------------------------------------------------------


def result(title: str = "Berlin") -> SearchResult:
    """A SearchResult identifiable by its title."""
    return SearchResult(
        chunk_id=f"{title}:0:0",
        doc_id=f"{title}:0",
        page_id=1,
        title=title,
        heading="History",
        text="The wall went up in 1961.",
        score=0.7,
        revision_id=42,
    )


class StubSearchService:
    """Answers with a fixed list and records what it was asked for."""

    def __init__(self, results: list[SearchResult]) -> None:
        self._results = results
        self.questions: list[tuple[str, int | None]] = []

    def search(
        self,
        question: str,
        k: int | None = None,
        min_score: float | None = None,
    ) -> list[SearchResult]:
        self.questions.append((question, k))
        return self._results


@pytest.fixture
def results() -> list[SearchResult]:
    return [result("Berlin"), result("Bonn"), result("Vienna")]


def service(
    results: list[SearchResult], answer: str
) -> tuple[GenerationService, StubSearchService]:
    """A GenerationService wired to a fixed search and a fixed answer."""
    search = StubSearchService(results)
    generator = FakeGenerator(answer=answer)
    return GenerationService(search, generator), search  # type: ignore[arg-type]


# --- reading citations out of an answer -------------------------------------


def test_a_marker_resolves_to_the_source_it_numbers(
    results: list[SearchResult],
) -> None:
    citations = cited("The wall went up [2].", results)

    assert [citation.number for citation in citations] == [2]
    assert citations[0].result.title == "Bonn"


def test_citations_come_back_in_the_order_the_answer_uses_them(
    results: list[SearchResult],
) -> None:
    citations = cited("Second [2], then first [1].", results)

    assert [citation.number for citation in citations] == [2, 1]


def test_a_source_cited_twice_is_listed_once(results: list[SearchResult]) -> None:
    """The list is what a reader clicks, not a count of mentions."""
    citations = cited("First [1]. Also first [1].", results)

    assert [citation.number for citation in citations] == [1]


def test_an_invented_number_is_dropped_rather_than_raising(
    results: list[SearchResult],
) -> None:
    """[7] with three sources is a prompt failure worth measuring in Phase 7,
    not a reason to throw away an otherwise usable answer.
    """
    citations = cited("Real [1], invented [7].", results)

    assert [citation.number for citation in citations] == [1]


def test_zero_is_not_a_source(results: list[SearchResult]) -> None:
    """Numbering starts at one, so [0] would silently return the last item."""
    assert cited("Nothing [0].", results) == []


def test_an_answer_with_no_markers_cites_nothing(
    results: list[SearchResult],
) -> None:
    assert cited("Not in the sources. The passages cover Berlin.", results) == []


# --- asking a question ------------------------------------------------------


def test_the_answer_carries_the_model_text_and_its_sources(
    results: list[SearchResult],
) -> None:
    generation, _ = service(results, "The wall went up in 1961 [1][3].")

    answer = generation.ask("why was the wall built?")

    assert isinstance(answer, Answer)
    assert answer.question == "why was the wall built?"
    assert answer.text == "The wall went up in 1961 [1][3]."
    assert [citation.result.title for citation in answer.citations] == [
        "Berlin",
        "Vienna",
    ]


def test_only_cited_sources_come_back(results: list[SearchResult]) -> None:
    """Three chunks were retrieved and one was used. The response lists one."""
    generation, _ = service(results, "Only the first [1].")

    assert len(generation.ask("why?").citations) == 1


def test_the_model_name_is_recorded_on_the_answer(
    results: list[SearchResult],
) -> None:
    """Phase 7 compares runs, and a run is only comparable if it says which
    model produced it.
    """
    generation, _ = service(results, "An answer [1].")

    assert generation.ask("why?").model == "fake-model"


def test_k_reaches_the_search(results: list[SearchResult]) -> None:
    generation, search = service(results, "An answer [1].")

    generation.ask("why?", k=3)

    assert search.questions == [("why?", 3)]


def test_the_retrieved_chunks_reach_the_model(results: list[SearchResult]) -> None:
    """The seam that matters: what search found is what the model is shown."""
    search = StubSearchService(results)
    generator = FakeGenerator(answer="An answer [1].")
    generation = GenerationService(search, generator)  # type: ignore[arg-type]

    generation.ask("why?")

    user = generator.calls[0][1]["content"]
    assert user.count("<source id=") == 3
    assert "why?" in user


def test_an_empty_retrieval_still_goes_to_the_model() -> None:
    """No shortcut, deliberately. One code path handles every refusal, so
    there is only one behaviour to test and to fix.
    """
    search = StubSearchService([])
    generator = FakeGenerator(answer="Not in the sources.")
    generation = GenerationService(search, generator)  # type: ignore[arg-type]

    answer = generation.ask("what is a transformer?")

    assert generator.calls != []
    assert answer.citations == []


def test_a_dead_model_surfaces_as_generation_unavailable(
    results: list[SearchResult],
) -> None:
    """The exception passes through untouched: turning it into a 503 is the
    API layer's job, not this service's.
    """
    from eurohistory_rag.generation.client import GenerationUnavailable

    generation = GenerationService(
        StubSearchService(results),  # type: ignore[arg-type]
        UnavailableGenerator(),
    )

    with pytest.raises(GenerationUnavailable):
        generation.ask("why?")
