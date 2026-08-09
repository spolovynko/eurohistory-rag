"""Tests for the answer path.

Nothing here calls a model. What is being checked is what we do with the text
a model returns -- which markers become sources, which are dropped, and what
reaches the caller -- not whether the model writes good history.
"""

import pytest

from eurohistory_rag.generation.rewrite import Turn
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


# --- the groundedness gate on the answer path -------------------------------

# A checker reply in the shape verify_prompt.md asks for: the working out
# first, then the answer. A fake returning bare text would test a reply the
# real prompt never produces.
CHECKED = """<check>
a claim -- SUPPORTED -- the source words
</check>
<answer>
{}
</answer>"""


def test_no_verifier_means_no_second_call(results: list[SearchResult]) -> None:
    """The default. A clean checkout must behave exactly as the run that
    measured 99.0% faithfulness did, or the before in the before/after moves.
    """
    generation, _ = service(results, "The wall went up in 1961 [1].")

    answer = generation.ask("when?")

    assert answer.revised is False
    assert answer.text == "The wall went up in 1961 [1]."


def test_the_verified_text_is_what_the_caller_gets(
    results: list[SearchResult],
) -> None:
    """The dead-switch test for the wiring. Phase 8 shipped a reranker that was
    unreachable and 337 tests passed, because every one of them asserted
    something true whether or not the feature ran. This one is false unless the
    verifier's text reaches the Answer.
    """
    checker = FakeGenerator(
        answer=CHECKED.format("The wall went up in August 1961 [1].")
    )
    generation = GenerationService(
        StubSearchService(results),  # type: ignore[arg-type]
        FakeGenerator(answer="The wall went up in 1961 [1]."),
        verifier=checker,
    )

    answer = generation.ask("when?")

    assert answer.text == "The wall went up in August 1961 [1]."
    assert answer.revised is True
    assert len(checker.calls) == 1


def test_both_calls_are_paid_for_in_one_number(results: list[SearchResult]) -> None:
    """Cost per question stays a true total, so metrics.py needs no change and
    the eval cannot under-report what this phase costs.
    """
    generation = GenerationService(
        StubSearchService(results),  # type: ignore[arg-type]
        FakeGenerator(answer="Draft [1].", prompt_tokens=100, completion_tokens=10),
        verifier=FakeGenerator(
            answer=CHECKED.format("Draft [1]."),
            prompt_tokens=200,
            completion_tokens=20,
        ),
    )

    answer = generation.ask("when?")

    assert answer.prompt_tokens == 300
    assert answer.completion_tokens == 30


def test_citations_follow_the_shipped_text_not_the_draft(
    results: list[SearchResult],
) -> None:
    """The gate may delete a sentence, and its marker goes with it. A citation
    list naming a source the answer no longer refers to is the kind of quiet
    inconsistency nobody notices until a reader clicks the link.
    """
    generation = GenerationService(
        StubSearchService(results),  # type: ignore[arg-type]
        FakeGenerator(answer="Berlin [1]. Something unsupported [2]."),
        verifier=FakeGenerator(answer=CHECKED.format("Berlin [1].")),
    )

    answer = generation.ask("when?")

    assert [citation.number for citation in answer.citations] == [1]


# --- streaming (Phase 21, D-095) ---------------------------------------------


def test_the_stream_yields_the_text_in_pieces_then_the_finished_answer(
    results: list[SearchResult],
) -> None:
    generation, _ = service(results, "The wall went up in 1961 [1].")

    pieces = list(generation.stream_from("when?", results))

    assert isinstance(pieces[-1], Answer)
    assert pieces[-1].text == "The wall went up in 1961 [1]."
    assert "".join(str(p) for p in pieces[:-1]) == "The wall went up in 1961 [1]."


def test_the_assembled_answer_is_the_streamed_one(
    results: list[SearchResult],
) -> None:
    """`answer_from` is the same call with the pieces thrown away, so the two
    shapes cannot drift apart into two different answers.
    """
    generation, _ = service(results, "Berlin [1].")

    assert generation.answer_from("when?", results).text == "Berlin [1]."


def test_a_streamed_answer_reports_when_its_first_word_arrived(
    results: list[SearchResult],
) -> None:
    generation = GenerationService(
        StubSearchService(results),  # type: ignore[arg-type]
        FakeGenerator(answer="Berlin [1].", first_token_ms=120.0),
    )

    assert generation.ask("when?").first_token_ms == 120.0


def test_nothing_streams_while_the_groundedness_gate_is_on(
    results: list[SearchResult],
) -> None:
    """You cannot stream text you may have to retract.

    The gate reads the finished draft and may delete a sentence from it, so the
    answer arrives in one piece and reports no first token -- which the eval
    reads as "arrived at the end" rather than as a fast one.
    """
    generation = GenerationService(
        StubSearchService(results),  # type: ignore[arg-type]
        FakeGenerator(answer="The wall went up in 1961 [1].", first_token_ms=120.0),
        verifier=FakeGenerator(answer=CHECKED.format("The wall went up [1].")),
    )

    pieces = list(generation.stream_from("when?", results))

    assert len(pieces) == 1
    assert isinstance(pieces[0], Answer)
    assert pieces[0].text == "The wall went up [1]."
    assert pieces[0].first_token_ms is None


# --- conversation -----------------------------------------------------------


def test_a_follow_up_is_resolved_before_anything_is_searched(
    results: list[SearchResult],
) -> None:
    """The one place the history is used, and the reason the rest is unchanged.

    Everything below this line -- retrieval, the answer prompt, the citations,
    every metric -- receives one self-contained question and cannot tell a
    second turn from a first.
    """
    search = StubSearchService(results)
    generation = GenerationService(
        search,  # type: ignore[arg-type]
        FakeGenerator(answer="It came down in 1989 [1]."),
        rewriter=FakeGenerator(answer="When did the Berlin Wall come down?"),
    )
    history = [Turn(user="Why was the Berlin Wall built?", assistant="To stop [1].")]

    resolved = generation.standalone("When did it come down?", history)

    assert resolved == "When did the Berlin Wall come down?"


def test_a_question_with_no_history_is_never_rewritten(
    results: list[SearchResult],
) -> None:
    """What keeps the 92 single-turn questions byte-identical.

    The rewriter is configured and would happily return something else; it is
    not called, because there is nothing to resolve.
    """
    rewriter = FakeGenerator(answer="something else entirely")
    generation = GenerationService(
        StubSearchService(results),  # type: ignore[arg-type]
        FakeGenerator(),
        rewriter=rewriter,
    )

    assert generation.standalone("What was the Marshall Plan?") == (
        "What was the Marshall Plan?"
    )
    assert rewriter.calls == []


def test_with_conversation_off_a_history_changes_nothing(
    results: list[SearchResult],
) -> None:
    """The before half of the before/after, as a test rather than as a promise."""
    generation = GenerationService(
        StubSearchService(results),  # type: ignore[arg-type]
        FakeGenerator(),
    )
    history = [Turn(user="Why was the Berlin Wall built?", assistant="To stop [1].")]

    assert generation.standalone("When did it come down?", history) == (
        "When did it come down?"
    )
